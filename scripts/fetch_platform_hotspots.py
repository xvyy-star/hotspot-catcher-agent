"""按平台直接抓取热点并导出 JSON / Markdown。

用途：
- 本地快速验证某个平台 connector 是否还能拿到真实数据。
- 单独展示“平台采集能力”，不必完整跑一遍今日早报。

示例：
    .\.venv\Scripts\python.exe scripts\fetch_platform_hotspots.py --sources github devto --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.connectors.public_apis import GitHubAPIConnector, HuggingFaceConnector, DevCommunityConnector  # noqa: E402


CONNECTORS = {
    "github": GitHubAPIConnector,
    "huggingface": HuggingFaceConnector,
    "devto": DevCommunityConnector,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取指定平台的系统关注热点并导出报告")
    parser.add_argument("--sources", nargs="+", default=["github", "huggingface", "devto"], choices=list(CONNECTORS), help="Official API source codes")
    parser.add_argument("--limit", type=int, default=20, help="每个平台最多抓取条数")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP 超时时间，单位秒")
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / "reports"), help="报告输出目录")
    return parser.parse_args()


def item_to_dict(item: Any) -> dict[str, Any]:
    return item.model_dump(mode="json")


def write_reports(result: dict[str, list[dict[str, Any]]], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_slug = "_".join(result.keys()) or "platform"
    json_path = out_dir / f"platform_hotspots_{source_slug}_{stamp}.json"
    md_path = out_dir / f"platform_hotspots_{source_slug}_{stamp}.md"

    json_path.write_text(
        json.dumps({"captured_at": now, "data": result}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Official API metadata report",
        "",
        f"- 抓取时间：{now}",
        "- Sources: GitHub REST API, Hugging Face Hub API, DEV Community API.",
        "- 过滤口径：只保留计算机行业 / AI 产品 / 开源技术 / 产业财经相关内容，不使用泛娱乐生活样例兜底。",
        "",
    ]
    for code, items in result.items():
        source_name = items[0].get("source_name") if items else code
        lines.append(f"## {source_name}（{len(items)} 条）")
        lines.append("")
        for item in items:
            hot = item.get("raw_hot_score") or "-"
            url = item.get("url") or ""
            content = item.get("content") or ""
            category = (item.get("raw_payload") or {}).get("system_category") or "系统关注"
            lines.append(f"{item.get('rank')}. {item.get('title')}  ")
            lines.append(f"   - 分类：{category}")
            lines.append(f"   - 热度/播放/点赞：{hot}")
            if content:
                lines.append(f"   - 说明：{content}")
            if url:
                lines.append(f"   - 链接：{url}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    args = parse_args()
    result: dict[str, list[dict[str, Any]]] = {}
    for source in args.sources:
        code = source.strip().lower()
        connector_cls = CONNECTORS.get(code)
        if not connector_cls:
            print(f"[SKIP] 未知平台：{source}")
            continue
        connector = connector_cls(max_items=max(1, args.limit), timeout=max(1, args.timeout))
        print(f"[FETCH] {connector.source_name} ...")
        items = connector.fetch()
        result[connector.source_code] = [item_to_dict(item) for item in items]
        print(f"[{'OK' if items else 'EMPTY/FAILED'}] {connector.source_name}: {len(items)} 条")

    json_path, md_path = write_reports(result, Path(args.out_dir))
    print(f"[JSON] {json_path}")
    print(f"[MD] {md_path}")
    for code, items in result.items():
        print()
        print(items[0].get("source_name") if items else code)
        for item in items[:10]:
            category = (item.get("raw_payload") or {}).get("system_category") or "系统关注"
            print(f"{item.get('rank'):>2}. {item.get('title')} | {category} | {item.get('raw_hot_score') or '-'}")
    return 0 if result and all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
