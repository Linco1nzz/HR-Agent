"""Alembic 迁移环境。

连接串来自 app.core.config.settings（即 backend/.env 的 DATABASE_URL）。
新增模型后请确保在 app/db/base.py（或其中导入的模块）被 target_metadata 感知。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.db.models  # noqa: F401  确保所有模型注册到 Base.metadata
from app.core.config import settings
from app.db.base import BaseModel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 转义 %，避免 configparser 对密码中的 % 做插值
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = BaseModel.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连接数据库。"""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：使用同步连接执行迁移。"""
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
