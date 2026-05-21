import pathlib
import tempfile
from pydantic import AfterValidator, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

yfinance_cache_dir = pathlib.Path(tempfile.gettempdir()) / "yfinance"

class ServerSettings(BaseSettings):
    REDIS_URL: str = Field(default="localhost:6379", description="URL for Redis connection")
    YFINANCE_CACHE_DIR: str = Field(default=str(yfinance_cache_dir), description="Directory for caching for yfinance")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

server_settings = ServerSettings()
