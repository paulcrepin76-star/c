import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    host_name: str = Field(default="Unraid", validation_alias=AliasChoices("HOST_NAME", "ORBIT_HOST"))
    public_url: str = Field(
        default="http://100.116.48.120:7575",
        validation_alias=AliasChoices("PUBLIC_URL", "ORBIT_URL"),
    )
    host_proc: str = "/proc"
    host_sys: str = "/sys"
    docker_socket: str = "unix:///var/run/docker.sock"
    data_dir: str = "/data"
    roots: str = ""
    shares: str = "/shares"
    cellar_url: str = "http://100.116.48.120:8088"
    paperless_url: str = "http://100.116.48.120:8011"
    mealie_url: str = "http://100.116.48.120:9925"
    n8n_url: str = "http://100.116.48.120:5678"
    metabase_url: str = "http://100.116.48.120:3001"
    homeassistant_url: str = "http://100.116.48.120:8123"
    frigate_url: str = "https://100.116.48.120:8971"
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    radarr_url: str = ""
    radarr_api_key: str = ""
    qbit_url: str = ""
    jellyfin_url: str = ""
    prowlarr_url: str = ""

    def root_map(self) -> dict[str, Path]:
        parsed: dict[str, Path] = {}
        raw = (os.environ.get("ORBIT_ROOTS") or os.environ.get("ROOTS") or self.roots or "").strip()
        if raw:
            for chunk in raw.split(","):
                if ":" not in chunk:
                    continue
                label, path = chunk.split(":", 1)
                label = label.strip()
                path = path.strip()
                if label and path:
                    parsed[label] = Path(path)
            return parsed
        shares = Path(self.shares)
        if shares.is_dir():
            for child in sorted(shares.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    parsed[child.name.replace("_", " ").title()] = child
            if parsed:
                return parsed
        fallback = Path(self.data_dir) / "files"
        fallback.mkdir(parents=True, exist_ok=True)
        parsed["Files"] = fallback
        return parsed


settings = Settings()
