import pathlib
import tempfile
from pydantic import AfterValidator, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

yfinance_cache_dir = pathlib.Path(tempfile.gettempdir()) / "yfinance"

class ServerSettings(BaseSettings):
    MCP_RESPONSE_CACHE_REDIS_URL: str = Field(default="redis://localhost:6379", description="URL for Redis connection for caching responses of MCP")
    API_RATELIMITING_REDIS_URL: str = Field(default="redis://localhost:6379", description="URL for Redis connection for rate limiting API requests")
    YFINANCE_CACHE_DIR: str = Field(default=str(yfinance_cache_dir), description="Directory for caching market data")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

server_settings = ServerSettings()
