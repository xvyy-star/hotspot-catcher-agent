"""今日早报推送服务。

当前推送目标改为 QQ 机器人，而不是本地 Spring Boot 项目。

第一版采用 OneBot v11 HTTP API 适配，原因：
- go-cqhttp、Lagrange.OneBot、NapCat、LiteLoaderQQNT 等方案都常见支持 OneBot 风格接口。
- 服务器部署时只需要把 `onebot_api_base` 指向机器人 HTTP 地址。
- 既可以发私聊 `send_private_msg`，也可以发群聊 `send_group_msg`。

交付说明：
- Agent 负责生成内容，Push Service 负责投递，二者解耦。
- 推送失败只写日志，默认不阻断早报生成，保证主链路可用。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.db.models import DailyBriefing, PushDeliveryLog
from app.schemas import BriefingDTO

logger = logging.getLogger(__name__)


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def apply_env_overrides(push_cfg: dict[str, Any]) -> dict[str, Any]:
    """服务器部署时允许用环境变量覆盖 YAML。

    这样你部署到服务器后，不需要改代码，也不需要把 QQ 号、token 写死进仓库。
    """
    cfg = dict(push_cfg or {})
    env_map = {
        "enabled": "HOTSPOT_PUSH_ENABLED",
        "channel": "HOTSPOT_PUSH_CHANNEL",
        "onebot_api_base": "HOTSPOT_QQ_BOT_API_BASE",
        "target_type": "HOTSPOT_QQ_BOT_TARGET_TYPE",
        "user_id": "HOTSPOT_QQ_BOT_USER_ID",
        "group_id": "HOTSPOT_QQ_BOT_GROUP_ID",
        "access_token": "HOTSPOT_QQ_BOT_ACCESS_TOKEN",
        "retry_times": "HOTSPOT_PUSH_RETRY_TIMES",
        "timeout_seconds": "HOTSPOT_PUSH_TIMEOUT_SECONDS",
        "max_chars": "HOTSPOT_PUSH_MAX_CHARS",
    }
    for key, env_name in env_map.items():
        value = os.getenv(env_name)
        if value is not None and value != "":
            cfg[key] = value
    return cfg


def _get_briefing_data(briefing: BriefingDTO | DailyBriefing | dict[str, Any]) -> dict[str, Any]:
    """把不同来源的早报对象转成 dict。"""
    if isinstance(briefing, BriefingDTO):
        return briefing.model_dump(mode="json")
    if isinstance(briefing, DailyBriefing):
        return briefing.raw_json or {
            "briefing_date": briefing.briefing_date.isoformat() if briefing.briefing_date else None,
            "title": briefing.title,
            "summary": briefing.summary,
            "markdown": briefing.markdown,
            "status": briefing.status,
        }
    return briefing


def build_briefing_text(briefing: BriefingDTO | DailyBriefing | dict[str, Any], max_chars: int = 3500) -> str:
    """构造 QQ 消息文本。

    QQ 消息不适合塞过长 Markdown，所以这里做了长度截断。
    后续如果接入图片卡片，可以把早报渲染成图片再发送。
    """
    data = _get_briefing_data(briefing)
    title = data.get("title") or "今日热点早报"
    summary = data.get("summary") or ""
    markdown = data.get("markdown") or ""
    events = data.get("events") or []

    lines: list[str] = []
    lines.append(str(title))
    if summary:
        lines.append("")
        lines.append(f"摘要：{summary}")
    lines.append("")
    lines.append("Top 热点：")
    for idx, event in enumerate(events[:10], start=1):
        if not isinstance(event, dict):
            continue
        risk = event.get("risk_level", "LOW")
        category = event.get("category", "综合")
        heat = event.get("heat_score", "-")
        event_title = event.get("title", "-")
        event_summary = event.get("summary") or ""
        lines.append(f"{idx}. [{category}/{risk}/热度{heat}] {event_title}")
        if event_summary:
            lines.append(f"   {event_summary[:120]}")

    if not events and markdown:
        lines.append(markdown[: max_chars // 2])

    lines.append("")
    lines.append("打开热点捕手后台可查看完整观点分析、风险原因和选题建议。")

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n...（已截断）"
    return text


def build_push_payload(
    briefing: BriefingDTO | DailyBriefing | dict[str, Any],
    run_id: str | None = None,
    *,
    message: str | None = None,
) -> dict[str, Any]:
    """构造推送日志中保存的标准 Payload。"""
    return {
        "source": "hotspot-catcher-agent",
        "channel": "qq-bot-onebot",
        "run_id": run_id,
        "pushed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "message": message or build_briefing_text(briefing),
        "briefing": _get_briefing_data(briefing),
    }


def _onebot_endpoint(push_cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """根据配置生成 OneBot API 地址和请求体。"""
    base_url = str(push_cfg.get("onebot_api_base") or "").strip().rstrip("/")
    target_type = str(push_cfg.get("target_type") or "private").strip().lower()
    user_id = str(push_cfg.get("user_id") or "").strip()
    group_id = str(push_cfg.get("group_id") or "").strip()

    if not base_url:
        raise ValueError("未配置 push.onebot_api_base")

    if target_type == "group":
        if not group_id:
            raise ValueError("target_type=group 时必须配置 push.group_id")
        if not group_id.isdigit():
            raise ValueError("push.group_id 必须是数字")
        return f"{base_url}/send_group_msg", {"group_id": int(group_id)}

    if not user_id:
        raise ValueError("target_type=private 时必须配置 push.user_id")
    if not user_id.isdigit():
        raise ValueError("push.user_id 必须是数字")
    return f"{base_url}/send_private_msg", {"user_id": int(user_id)}


def _onebot_headers(push_cfg: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    access_token = str(push_cfg.get("access_token") or "").strip()
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _onebot_response_ok(body: Any) -> tuple[bool, str]:
    """Interpret common OneBot response shapes without treating failures as success."""
    if not isinstance(body, dict):
        return False, "OneBot 返回内容不是 JSON 对象"
    if not body:
        return True, ""

    if "retcode" in body:
        retcode = body.get("retcode")
        return retcode in {0, "0"}, f"OneBot retcode={retcode}: {body.get('wording') or body}"

    if "status" in body:
        status = str(body.get("status") or "").strip().lower()
        return status in {"ok", "success"}, f"OneBot status={status or '-'}: {body.get('wording') or body}"

    if isinstance(body.get("data"), dict) and body.get("data"):
        return True, ""
    return False, f"OneBot 返回缺少成功标识：{body}"


def test_onebot_connection(push_cfg: dict[str, Any]) -> dict[str, Any]:
    """测试 OneBot HTTP API 连通性，不发送 QQ 消息。"""
    cfg = apply_env_overrides(push_cfg or {})
    base_url = str(cfg.get("onebot_api_base") or "").strip().rstrip("/")
    timeout_seconds = max(1, int(cfg.get("timeout_seconds") or 5))
    if not base_url:
        return {"ok": False, "message": "未配置 onebot_api_base"}
    try:
        _onebot_endpoint(cfg)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}

    target_url = f"{base_url}/get_login_info"
    started = time.perf_counter()
    try:
        resp = requests.post(target_url, json={}, headers=_onebot_headers(cfg), timeout=timeout_seconds)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not (200 <= resp.status_code < 300):
            return {
                "ok": False,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "message": f"HTTP {resp.status_code}: {resp.text[:300]}",
            }
        body = resp.json() if resp.text else {}
        ok, protocol_message = _onebot_response_ok(body)
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "message": "OneBot 连通成功" if ok else protocol_message,
            "data": body.get("data") if isinstance(body, dict) else body,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": str(exc),
        }


def push_briefing(
    db: Session,
    *,
    briefing: BriefingDTO | DailyBriefing | dict[str, Any],
    run_id: str | None,
    push_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """按配置推送早报到 QQ 机器人并落库推送日志。"""
    push_cfg = apply_env_overrides(push_cfg or {})
    enabled = _bool_value(push_cfg.get("enabled"), default=False)
    channel = str(push_cfg.get("channel") or "qq_bot").strip().lower()
    retry_times = max(1, int(push_cfg.get("retry_times") or 1))
    timeout_seconds = max(1, int(push_cfg.get("timeout_seconds") or 5))
    access_token = str(push_cfg.get("access_token") or "").strip()
    max_chars = max(500, int(push_cfg.get("max_chars") or 3500))

    if isinstance(briefing, BriefingDTO):
        briefing_date = briefing.briefing_date
    elif isinstance(briefing, DailyBriefing):
        briefing_date = briefing.briefing_date
    else:
        raw_date = briefing.get("briefing_date")
        briefing_date = date.fromisoformat(raw_date) if raw_date else None

    try:
        target_url, target_payload = _onebot_endpoint(push_cfg)
    except Exception as exc:  # noqa: BLE001
        target_url = str(push_cfg.get("onebot_api_base") or "")
        target_payload = {}
        config_error = str(exc)
    else:
        config_error = ""

    message = build_briefing_text(briefing, max_chars=max_chars)
    request_payload = build_push_payload(briefing, run_id=run_id, message=message)
    row = PushDeliveryLog(
        run_id=run_id,
        briefing_date=briefing_date,
        target_url=target_url or None,
        status="PENDING",
        attempts=0,
        request_payload=request_payload,
    )
    db.add(row)
    db.flush()

    if not enabled:
        row.status = "SKIPPED"
        row.error_message = "push.enabled=false，已跳过自动推送"
        return {"status": "SKIPPED", "message": row.error_message, "attempts": 0, "target_url": target_url}

    if channel not in {"qq_bot", "onebot"}:
        row.status = "SKIPPED"
        row.error_message = f"暂不支持的推送通道：{channel}"
        return {"status": "SKIPPED", "message": row.error_message, "attempts": 0, "target_url": target_url}

    if config_error:
        row.status = "FAILED"
        row.error_message = config_error
        return {"status": "FAILED", "message": config_error, "attempts": 0, "target_url": target_url}

    headers = _onebot_headers(push_cfg)

    onebot_body = {**target_payload, "message": message, "auto_escape": False}
    last_error = ""
    last_status: int | None = None
    for attempt in range(1, retry_times + 1):
        row.attempts = attempt
        try:
            resp = requests.post(target_url, json=onebot_body, headers=headers, timeout=timeout_seconds)
            last_status = resp.status_code
            row.http_status = resp.status_code
            row.response_text = resp.text[:2000]
            if 200 <= resp.status_code < 300:
                body = resp.json() if resp.text else {}
                ok, protocol_message = _onebot_response_ok(body)
                if ok:
                    row.status = "SUCCESS"
                    row.error_message = None
                    return {
                        "status": "SUCCESS",
                        "message": "早报已推送到 QQ 机器人",
                        "attempts": attempt,
                        "target_url": target_url,
                        "http_status": resp.status_code,
                    }
                last_error = protocol_message
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            logger.warning("QQ 机器人早报推送失败，第 %s/%s 次: %s", attempt, retry_times, exc)
        if attempt < retry_times:
            time.sleep(min(2, attempt))

    row.status = "FAILED"
    row.http_status = last_status
    row.error_message = last_error[:1000]
    return {
        "status": "FAILED",
        "message": last_error,
        "attempts": retry_times,
        "target_url": target_url,
        "http_status": last_status,
    }
