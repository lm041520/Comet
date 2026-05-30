"""应用配置：全部从环境变量 / .env 读取，不硬编码。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 应用
    app_name: str = "Comet"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # 安全
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    fernet_key: str = "change-me-fernet-key"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "comet"
    postgres_password: str = "comet"
    postgres_db: str = "comet"
    # PG 连接池
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30  # 取连接超时（秒）
    db_pool_recycle: int = 1800  # 连接回收（秒），防被 DB 端断开
    db_pool_pre_ping: bool = True  # 取连接前 ping，剔除失效连接
    db_statement_timeout_ms: int = 60000  # 单条 SQL 超时（毫秒）

    # Elasticsearch
    es_host: str = "http://localhost:9200"
    es_username: str = ""
    es_password: str = ""
    es_max_retries: int = 3
    es_request_timeout: int = 30  # 秒
    es_max_connections: int = 25

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "cometneo4j"
    neo4j_max_pool_size: int = 50
    neo4j_connection_timeout: int = 30  # 秒

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # 文件存储
    storage_backend: str = "local"  # local | oss
    storage_dir: str = "./storage"

    # 阿里云 OSS
    oss_endpoint: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket_name: str = ""

    # 日志
    log_level: str = "INFO"  # DEBUG/INFO/WARNING/ERROR
    log_to_console: bool = True
    log_to_file: bool = True
    log_file_path: str = "./logs/comet.log"
    log_max_bytes: int = 10 * 1024 * 1024  # 单文件 10MB
    log_backup_count: int = 5  # 轮转保留份数
    db_echo: bool = False  # 是否打印 SQL（调试用，默认关，避免日志刷屏）

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
