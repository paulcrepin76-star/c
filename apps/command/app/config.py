from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/command.db"
    command_secret_key: str = ""
    command_admin_email: str = ""
    command_admin_password: str = ""
    command_api_key: str = ""
    resto_api_key: str = ""
    command_public_url: str = "http://127.0.0.1:8090"
    command_https_only: bool = False
    mautic_internal_url: str = "http://mautic"
    postiz_internal_url: str = "http://postiz:5000"
    n8n_internal_url: str = "http://n8n:5678"
    ollama_base_url: str = ""
    ollama_text_model: str = ""
    ollama_vision_model: str = ""
    data_dir: str = "data"
    probe_timeout: float = 3.0
    google_ads_api_version: str = "v18"
    meta_graph_version: str = "v21.0"


settings = Settings()
