from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


class ServerConfig(BaseModel):
    host: str
    user: str
    port: int = 22
    key_path: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Seravops"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://seravops:seravops@postgres:5432/seravops"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    server_1_host: str = "localhost"
    server_1_user: str = "root"
    server_1_port: int = 22
    server_1_key_path: str | None = None
    server_2_host: str = "localhost"
    server_2_user: str = "root"
    server_2_port: int = 22
    server_2_key_path: str | None = None

    template_dir: Path = BASE_DIR / "templates"
    static_dir: Path = BASE_DIR / "static"

    def server(self, name: str) -> ServerConfig:
        if name not in {"server_1", "server_2"}:
            raise ValueError(f"Unknown target server: {name}")
        return ServerConfig(
            host=getattr(self, f"{name}_host"),
            user=getattr(self, f"{name}_user"),
            port=getattr(self, f"{name}_port"),
            key_path=getattr(self, f"{name}_key_path"),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
