from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Grok (xAI). Leave the key empty and the bot still answers plain commands.
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-4.6"
    grok_timeout: float = 120.0
    grok_max_rounds: int = 6

    # Telegram. The bot polls out to Telegram, so Unraid needs no open port.
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    telegram_poll_seconds: int = 30
    # Only change this to run against a self-hosted Bot API server.
    telegram_api_base: str = "https://api.telegram.org"

    # resto-core, for the restaurant half of the answers.
    resto_url: str = "http://resto-core:8080"
    resto_api_key: str = ""
    # LAN or Tailscale address, used when the bot tells you where a new app lives.
    public_url: str = ""

    # Server control.
    docker_socket: str = "/var/run/docker.sock"
    repo_dir: str = "/mnt/user/appdata/resto"
    compose_project: str = "resto"
    appdata_dir: str = "/mnt/user/appdata/resto"
    data_dir: str = "/data"
    compose_timeout: int = 900

    require_confirm: bool = True
    allow_custom_images: bool = True
    confirm_ttl_seconds: int = 600
    history_turns: int = 12
    timezone: str = "America/New_York"

    @property
    def allowed_chat_ids(self) -> set[str]:
        raw = self.telegram_allowed_chat_ids.replace(";", ",")
        return {part.strip() for part in raw.split(",") if part.strip()}

    @property
    def grok_enabled(self) -> bool:
        return bool(self.xai_api_key)


settings = Settings()
