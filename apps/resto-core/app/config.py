from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://resto:resto@localhost:5432/resto"
    secret_key: str = "dev-secret-change-me"
    resto_api_key: str = "dev-api-key"
    timezone: str = "America/New_York"

    resto_public_url: str = "http://100.116.48.120:8088"
    resto_oauth_url: str = ""
    mealie_base_url: str = "http://host.docker.internal:9925"
    mealie_api_token: str = ""
    square_access_token: str = ""
    square_environment: str = "production"
    square_location_id: str = ""
    square_application_id: str = ""
    square_application_secret: str = ""
    paperless_base_url: str = "http://host.docker.internal:8011"
    paperless_api_token: str = ""
    paperless_public_url: str = ""
    catalog_scan_enabled: bool = True
    open_prices_enabled: bool = True
    bls_enabled: bool = True
    usda_mmn_api_key: str = ""
    home_market: str = "Bonita Springs, Florida"
    home_lat: float = 26.3398
    home_lon: float = -81.7787
    price_gap_pct: float = 8.0
    collector_url: str = ""
    collector_vnc_url: str = "http://100.116.48.120:7900"
    frigate_public_url: str = "https://100.116.48.120:8971"
    frigate_internal_url: str = "http://resto-frigate:5000"
    frigate_magicdns_url: str = "https://lerouxfamily.tailbd3356.ts.net:8971"
    quickbooks_client_id: str = ""
    quickbooks_client_secret: str = ""
    quickbooks_environment: str = "production"


settings = Settings()
