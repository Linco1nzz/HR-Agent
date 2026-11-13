"""应用配置：从环境变量与 backend/.env 读取。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（本文件位于 backend/app/core/config.py）
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """全局配置。环境变量名不区分大小写，例如 APP_ENV 对应 app_env。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 应用 ---
    app_name: str = "HR-Agent API"
    app_env: Literal["development", "testing", "production"] = "development"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 18080
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- 数据库（PostgreSQL 17 + pgvector，宿主机端口 5433）---
    database_url: str = (
        "postgresql+psycopg://hr_agent_user:hr_agent_password@localhost:5433/hr_agent"
    )
    db_host: str = "localhost"
    db_port: int = 5433
    db_user: str = "hr_agent_user"
    db_password: str = "hr_agent_password"
    db_name: str = "hr_agent"

    # --- 缓存 / 任务队列 ---
    redis_url: str = "redis://localhost:6379/0"

    # --- 鉴权 ---
    # HS256 建议密钥不短于 32 字节；生产环境必须替换为随机密钥
    jwt_secret: str = "change-me-in-production-please-32bytes"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # --- 密码哈希（Argon2id，内存单位 KiB）---
    # 默认低于 argon2-cffi 的 64 MiB / 3 次 / 4 并行，可按机器性能调整；
    # 生产环境可适当调高（OWASP 最低建议为 19 MiB / 2 次 / 1 并行）。
    argon2_time_cost: int = 2
    argon2_memory_cost: int = 32768
    argon2_parallelism: int = 2

    # --- LLM：DeepSeek（判断知识库文档的语义分割点）---
    #: 从系统环境变量 DEEPSEEK_API_KEY 读取
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-flash"
    #: DeepSeek Flash 会先输出 reasoning_content，需为 JSON 结果留足 token
    deepseek_max_tokens: int = 2048
    #: 推理强度：low / high / max；切分点判断用 low 即可
    deepseek_reasoning_effort: str = "low"
    #: 单次分割点判断的最长等待时间（秒）
    deepseek_timeout_seconds: float = 120.0

    # --- Embedding：阿里云百炼 DashScope 兼容模式 ---
    #: 从系统环境变量 DASHSCOPE_API_KEY 读取
    dashscope_api_key: str | None = None
    embedding_base_url: str = (
        "https://llm-krcikrn4mpgwujad.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    embedding_model: str = "qwen3.7-text-embedding"
    #: 必须与 langchain_pg_embedding 向量列维度一致
    embedding_dim: int = 1024
    #: 单次请求 embedding 接口的文本条数
    embedding_batch_size: int = 16

    # --- 向量存储：LangChain PGVector（langchain_pg_embedding 表）---
    #: 知识库分块统一存入该 collection，按 cmetadata.document_id 区分文档
    pgvector_collection_name: str = "hr_agent_kb_chunks"

    # --- Dify Chatflow（advanced-chat 应用，API 前缀需包含 /v1）---
    dify_base_url: str = "http://127.0.0.1/v1"
    dify_api_key: str | None = None
    #: 单次工作流允许的最长等待时间（LLM 生成可能较慢）
    dify_timeout_seconds: float = 120.0
    dify_connect_timeout_seconds: float = 5.0

    # --- 简历文件上传 ---
    #: 简历附件保存目录；相对路径按 backend/ 解析
    resume_upload_dir: str = str(BACKEND_DIR / "uploads" / "resumes")
    #: 单份简历允许的最大体积（MB）
    resume_max_file_size_mb: int = 10

    # --- 知识库文档上传与切块 ---
    #: 知识库文档保存目录；相对路径按 backend/ 解析
    knowledge_base_upload_dir: str = str(BACKEND_DIR / "uploads" / "knowledge_bases")
    #: 单份文档允许的最大体积（MB）
    knowledge_base_max_file_size_mb: int = 20
    #: 单个分块的目标长度（字符）；中文场景按字符而非 token 计
    knowledge_base_chunk_size: int = 800
    #: 相邻分块的重叠长度（字符），避免边界语义被切断
    knowledge_base_chunk_overlap: int = 120
    #: 小于该长度的分块尽量并入前一块
    knowledge_base_min_chunk_chars: int = 80
    #: 单份文档最多保留的分块数量，超出部分丢弃并记录日志
    knowledge_base_max_chunks: int = 500
    #: 交给 LLM 判断语义分割点时允许的最大字符数，过长文本只取前段
    knowledge_base_llm_split_max_chars: int = 12_000

    # --- CORS（逗号分隔的前端地址）---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """把 CORS_ORIGINS 拆成列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """返回缓存的配置单例（测试中可 get_settings.cache_clear()）。"""
    return Settings()


settings = get_settings()
