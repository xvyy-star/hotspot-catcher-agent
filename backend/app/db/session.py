"""
数据库会话管理。

这里使用 SQLAlchemy + PyMySQL 连接 MySQL。
为什么第一版不用异步 ORM？
- MVP 阶段同步 ORM 更容易调试。
- 热点早报是定时批处理，不是高并发交易系统。
- 后续如果并发压力上来，可以迁移到 async SQLAlchemy。

P0-3: 启动时不再执行 ALTER TABLE 补列迁移。所有结构变更统一走 Alembic。
       首次开发环境允许 create_all 建表（AUTO_CREATE_TABLES=true）；
       生产环境应设置 AUTO_CREATE_TABLES=false 并执行 `alembic upgrade head`。
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connection_options = (
    {"check_same_thread": False, "timeout": 30}
    if make_url(settings.database_url).get_backend_name() == "sqlite"
    else {"connect_timeout": 10, "read_timeout": 60, "write_timeout": 60}
)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,     # 连接断开时自动探活，避免 MySQL 长连接失效导致请求报错。
    pool_recycle=1800,      # MySQL wait_timeout 前主动回收连接。
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    connect_args=connection_options,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def init_db() -> None:
    """初始化数据库表。

    P0-3: 移除了 ensure_lightweight_migrations()。
    - 开发环境（AUTO_CREATE_TABLES=true）：使用 Base.metadata.create_all 建表。
    - 生产环境（AUTO_CREATE_TABLES=false）：必须先执行 `alembic upgrade head`。
    """
    from app.db import models  # noqa: F401

    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    else:
        # 生产模式：只验证数据库可连通，不自动建表
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))


def get_db():
    """FastAPI 依赖：每个请求独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
