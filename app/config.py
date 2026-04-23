from functools import lru_cache

import structlog
from pydantic_settings import BaseSettings


_DEFAULT_SECRET = "change-me"

logger = structlog.get_logger()


class Settings(BaseSettings):
    app_env: str = "development"
    app_debug: bool = False
    app_port: int = 8000
    app_secret_key: str = _DEFAULT_SECRET
    # Comma-separated allowed CORS origins (e.g. "https://example.com,https://staging.example.com")
    allowed_origins: str = ""
    # Comma-separated CORS allowed origins (additive to the built-in defaults).
    cors_allowed_origins: str = ""
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
    telemetry_ingest_token: str = ""

    # Observability (Sentry)
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    # Gemini / Finance Assessment (Phase-1)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    finance_llm_enabled: bool = False
    finance_llm_max_pdf_mb: int = 10
    finance_llm_monthly_budget_usd: float = 50.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Vercel cold start must still boot even when the secret is unset, so we
    # log loudly instead of raising. Production deploys must override this.
    if s.app_env.lower() == "production" and s.app_secret_key == _DEFAULT_SECRET:
        logger.critical(
            "insecure_app_secret_key",
            app_env=s.app_env,
            message="APP_SECRET_KEY is set to the default placeholder in production. "
                    "Generate a new value with `python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
                    "and set APP_SECRET_KEY in the deployment environment.",
        )
    return s


def parse_allowed_origins(raw: str) -> list[str]:
    """Parse a comma-separated origin list env value into a clean list."""
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]
