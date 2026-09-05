"""
应用配置中心。

为什么单独放 config.py？
企业级项目不能把数据库地址、AI Key、调度时间写死在业务代码里。
统一配置后，本地开发、测试环境、服务器部署都可以通过环境变量切换。
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_local_env() -> None:
    """加载项目根目录下的 .env。

    这里不引入 python-dotenv，是为了让项目依赖更轻。
    规则也很简单：只读取 KEY=VALUE，且不覆盖系统环境变量。
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()


@dataclass(frozen=True)
class Settings:
    """热点捕手 Agent 全局配置。"""

    app_name: str = "Hotspot Catcher Agent"
    api_prefix: str = "/api"
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()

    # MySQL 连接地址。
    database_url: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://hotspot:hotspot123@localhost:3307/hotspot_agent?charset=utf8mb4",
    )

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6380/1")

    # OpenAI-compatible 大模型配置。没有 Key 时会自动走规则分析兜底，保证本地演示不会挂。
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_base_url: str = os.getenv("AI_BASE_URL", "")
    ai_model: str = os.getenv("AI_MODEL", "")

    # 是否开启后台定时任务。开发期也可以通过接口手动触发。
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
    daily_hour: int = int(os.getenv("DAILY_BRIEFING_HOUR", "8"))
    daily_minute: int = int(os.getenv("DAILY_BRIEFING_MINUTE", "0"))

    # 采集源配置文件路径。
    sources_config_path: Path = Path(
        os.getenv("HOTSPOT_SOURCES_CONFIG", str(PROJECT_ROOT / "config" / "sources.example.yml"))
    )

    # 知识库 / RAG 配置。
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "hotspot_knowledge_chunks")

    # Embedding 配置。
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "384"))
    embedding_timeout_seconds: int = int(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60"))

    # ------------------------------------------------------------------
    # 交付态安全配置
    # ------------------------------------------------------------------
    # P0-4: 默认值改为空字符串；生产环境未配置时启动校验会拒绝启动。
    # 开发环境可通过 .env 设置，测试环境通过 os.environ.setdefault 设置。
    api_auth_enabled: bool = _env_bool("API_AUTH_ENABLED", "true")

    # ADMIN_TOKEN 仅用于服务间 API 调用（非登录会话），不再从 login 接口返回。
    admin_token: str = os.getenv("ADMIN_TOKEN", "")

    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_display_name: str = os.getenv("ADMIN_DISPLAY_NAME", "系统管理员")
    admin_role: str = os.getenv("ADMIN_ROLE", "owner")

    # P0-7: 密码校验优先使用 bcrypt 哈希（ADMIN_PASSWORD_BCRYPT）。
    # ADMIN_PASSWORD_SHA256 作为已部署环境过渡兼容（已标记弃用）。
    # 明文 ADMIN_PASSWORD 已移除，不再支持。
    admin_password: str = ""  # 已弃用，保留字段仅为向后兼容读取，不再用于校验
    admin_password_bcrypt: str = os.getenv("ADMIN_PASSWORD_BCRYPT", "")
    admin_password_sha256: str = os.getenv("ADMIN_PASSWORD_SHA256", "")

    # APP_SECRET_KEY 用于敏感字段加密；未配置时使用 ADMIN_TOKEN 兜底（仅限开发）。
    app_secret_key: str = os.getenv("APP_SECRET_KEY", "")

    auth_exempt_paths: tuple[str, ...] = ("/api/system/status", "/api/auth/login")
    login_failure_limit: int = int(os.getenv("LOGIN_FAILURE_LIMIT", "5"))
    login_lock_seconds: int = int(os.getenv("LOGIN_LOCK_SECONDS", "300"))

    # 会话 token 有效期（秒）。
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", str(8 * 3600)))
    session_remember_ttl_seconds: int = int(os.getenv("SESSION_REMEMBER_TTL_SECONDS", str(30 * 24 * 3600)))

    # 同一天只允许一个异步早报任务占用生成槽，防止重复点击造成重复采集和模型费用。
    briefing_task_lock_seconds: int = int(os.getenv("BRIEFING_TASK_LOCK_SECONDS", str(4 * 3600)))
    # Redis 调度锁异常时默认停止任务，防止多实例退化成本地锁后重复生成。
    scheduler_lock_fail_open: bool = _env_bool("SCHEDULER_LOCK_FAIL_OPEN", "false")

    # 简单限流：防止误触生成/推送/探测导致 API 费用或外部站点压力失控。
    # P0-2: 限流计数已迁移到 Redis，多 worker/多实例共享。
    rate_limit_enabled: bool = _env_bool("RATE_LIMIT_ENABLED", "true")
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    rate_limit_read_per_window: int = int(os.getenv("RATE_LIMIT_READ_PER_WINDOW", "240"))
    rate_limit_write_per_window: int = int(os.getenv("RATE_LIMIT_WRITE_PER_WINDOW", "40"))
    # 限流「失效降级」策略：Redis 不可用时是否放行请求。
    # 默认 false = fail-closed（拒绝并告警），避免限流静默失效导致高成本接口被刷爆。
    # 仅在明确接受风险时才设为 true。
    rate_limit_fail_open: bool = _env_bool("RATE_LIMIT_FAIL_OPEN", "false")

    # 反向代理层数：项目自带 nginx 反代，真实客户端 IP 需从 X-Forwarded-For 解析。
    # 默认不信任代理头；生产 Compose 在一层 nginx 后显式设为 1。
    # 注意：值必须与实际可信代理层数一致，否则会被伪造的 XFF 头绕过。
    trusted_proxy_count: int = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))

    # 实时数据源探测缓存，避免健康页反复点击时连续打外部公开源。
    live_probe_cache_seconds: int = int(os.getenv("LIVE_PROBE_CACHE_SECONDS", "60"))
    # 历史采集结果超过该时长后不再标记为健康。
    source_health_stale_hours: int = int(os.getenv("SOURCE_HEALTH_STALE_HOURS", "36"))

    # P0-8: 生产环境关闭自动文档。
    docs_enabled: bool = _env_bool("DOCS_ENABLED", "false")

    # P0-3: 启动时是否自动建表（仅 dev）；生产应使用 alembic upgrade head。
    auto_create_tables: bool = _env_bool("AUTO_CREATE_TABLES", "true")

    # 跨域：前端 Vite 默认 5173，生产环境可通过 CORS_ORIGINS 逗号分隔覆盖。
    cors_origins: tuple[str, ...] = _split_csv(
        os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
        )
    )

    def validate_for_startup(self) -> list[str]:
        """启动前校验关键安全配置，返回阻塞原因列表（空列表表示通过）。

        P0-4: 生产环境未配置关键凭据时拒绝启动。
        """
        issues: list[str] = []
        if self.api_auth_enabled:
            # 开发环境允许通过 ADMIN_TOKEN 直接访问 API（服务间调用），
            # 但如果既没有 ADMIN_TOKEN 也没有密码哈希，则无法登录也无法鉴权。
            has_token = bool(self.admin_token.strip())
            has_password = bool(self.admin_password_bcrypt.strip() or self.admin_password_sha256.strip())
            if not has_token and not has_password:
                issues.append(
                    "API_AUTH_ENABLED=true 但未配置 ADMIN_TOKEN 或 ADMIN_PASSWORD_BCRYPT，"
                    "无法进行 API 鉴权或登录。请设置 ADMIN_TOKEN 和 ADMIN_PASSWORD_BCRYPT。"
                )
        return issues


settings = Settings()
