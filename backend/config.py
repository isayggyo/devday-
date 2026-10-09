from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore",
        hide_input_in_errors=True,
    )
    app_env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development", "jwt"] = "development"
    database_url: SecretStr = SecretStr("")
    test_database_url: SecretStr = SecretStr("")
    frontend_origin: str = "http://127.0.0.1:3000"
    e2e_mode: bool = False
    openai_api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def production_auth(self):
        if self.app_env == "production" and self.auth_mode == "development":
            raise ValueError("Development authentication is not permitted in production")
        return self

    def ai_key(self) -> SecretStr:
        if self.openai_api_key.get_secret_value():
            return self.openai_api_key
        local_file = ROOT / "api key.txt"
        if local_file.is_file() and self.app_env != "production":
            match = re.search(r"sk-[A-Za-z0-9_-]{20,}", local_file.read_text(encoding="utf-8-sig", errors="ignore"))
            if match:
                return SecretStr(match.group(0))
        return SecretStr("")


@lru_cache
def get_settings():
    return Settings()
