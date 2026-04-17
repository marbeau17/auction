from pydantic_settings import BaseSettings
from functools import lru_cache


_DEFAULT_SECRET = "change-me"


class Settings(BaseSettings):
    app_env: str = "development"
    app_debug: bool = False
    app_port: int = 8000
    app_secret_key: str = _DEFAULT_SECRET
    # Comma-separated allowed CORS origins (e.g. "https://example.com,https://staging.example.com")
    allowed_origins: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""
    supabase_jwt_secret: str = ""
    scraper_request_interval_sec: int = 3
    scraper_max_retries: int = 3
    scraper_user_agent: str = "CommercialVehicleResearchBot/1.0"

    # SMTP / Email settings
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = "noreply@cvlpos.jp"
    from_name: str = "CVLPOS 請求管理システム"
    email_dry_run: bool = True

    # Yayoi Accounting Online API
    yayoi_client_id: str = ""
    yayoi_client_secret: str = ""
    yayoi_redirect_uri: str = ""
    yayoi_enabled: bool = False

    # Financial Analysis
    financial_analysis_enabled: bool = True
    max_lease_to_ocf_ratio: float = 0.30
    max_lease_to_revenue_ratio: float = 0.05

    # Telemetry ingest (Phase 3a)
    # Shared secret presented by telematics devices / gateway in the
    # X-Device-Token header. Leave empty to disable the ingest endpoints
    # (fail-closed).
    telemetry_ingest_token: str = ""

    # Observability (Sentry)
    # Leave blank to disable Sentry entirely (no-op init). When set, errors
    # and traces are shipped to Sentry with the given traces sample rate.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # In non-development environments, refuse to boot with the placeholder secret.
    if s.app_env.lower() not in {"development", "dev", "local", "test"} and s.app_secret_key == _DEFAULT_SECRET:
        raise RuntimeError(
            "APP_SECRET_KEY must be set to a non-default value when APP_ENV is not development/test."
        )
    return s


def parse_allowed_origins(raw: str) -> list[str]:
    """Parse the ALLOWED_ORIGINS comma-separated env value into a clean list."""
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]
