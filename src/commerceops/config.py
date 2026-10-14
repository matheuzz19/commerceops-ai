from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    database_url: str = "postgresql+psycopg://commerceops:commerceops@localhost:5432/commerceops"
    redis_url: str = "redis://localhost:6379/0"
    langsmith_api_key: str | None = None
    langsmith_tracing: bool = False
    langsmith_project: str = "commerceops-ai-m4"
    llm_input_usd_per_million: Decimal | None = Field(default=None, ge=0)
    llm_output_usd_per_million: Decimal | None = Field(default=None, ge=0)
    default_tenant_timezone: str = "UTC"
    message_debounce_seconds: float = Field(default=3, ge=0)
    session_lock_seconds: float = Field(default=60, ge=1)
    max_batch_write: int = 5
    large_inventory_movement: int = 100
    large_transaction_amount: Decimal = Field(default=Decimal("1000.00"))


settings = Settings()
