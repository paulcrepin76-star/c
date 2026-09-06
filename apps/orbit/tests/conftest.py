import os
from pathlib import Path

ROOT = Path("/tmp/orbit-pytest-files")
(ROOT / "documents").mkdir(parents=True, exist_ok=True)
(ROOT / "library" / "Films").mkdir(parents=True, exist_ok=True)
(ROOT / "library" / "Series").mkdir(parents=True, exist_ok=True)
(ROOT / "grabs").mkdir(parents=True, exist_ok=True)
(ROOT / "documents" / "note.txt").write_text("invoice drop")
(ROOT / "library" / "Films" / "demo.mkv").write_text("film")
(ROOT / "grabs" / "incoming.bin").write_text("grab")

os.environ.setdefault("HOST_NAME", "test-box")
os.environ["ROOTS"] = (
    f"Documents:{ROOT / 'documents'},Library:{ROOT / 'library'},Grabs:{ROOT / 'grabs'}"
)
os.environ.setdefault("DATA_DIR", str(ROOT))
os.environ.setdefault("SHARES", str(ROOT))
os.environ["SONARR_URL"] = ""
os.environ["RADARR_URL"] = ""
os.environ["QBIT_URL"] = ""
os.environ["JELLYFIN_URL"] = ""
