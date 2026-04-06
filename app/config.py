from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_env: str = "development"
    app_debug: bool = False
    app_port: int = 8000
    app_secret_key: str = "change-me"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""
    supabase_jwt_secret: str = ""
    scraper_request_interval_sec: int = 3
    scraper_max_retries: int = 3
    scraper_user_agent: str = "CommercialVehicleResearchBot/1.0"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
