from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NeoMarket B2B Seller Cabinet"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "neomarket_b2b"
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_echo: bool = False

    jwt_secret_key: str = "dev-secret"
    jwt_algorithm: str = "HS256"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

