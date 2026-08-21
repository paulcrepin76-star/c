from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://resto:resto@localhost:5432/resto"
    secret_key: str = "dev-secret-change-me"
    resto_api_key: str = "dev-api-key"
    timezone: str = "America/New_York"

    mealie_base_url: str = ""
    mealie_api_token: str = ""
    square_access_token: str = ""
    square_environment: str = "production"
    square_location_id: str = ""
    paperless_base_url: str = ""
    paperless_api_token: str = ""
    paperless_public_url: str = ""
    ollama_base_url: str = ""


settings = Settings()
