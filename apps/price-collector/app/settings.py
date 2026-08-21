from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    resto_url: str = "http://resto-core:8080"
    resto_api_key: str = ""
    data_dir: str = "/data"
    timezone: str = "America/New_York"
    scan_hour: int = 2
    scan_minute: int = 0
    pause_seconds: float = 1.5
    per_supplier_limit: int = 25
    page_timeout_ms: int = 25000


settings = Settings()
