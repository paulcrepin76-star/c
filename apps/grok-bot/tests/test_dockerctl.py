from pathlib import Path

from app import dockerctl
from app.settings import settings

CONTAINERS = [
    {"name": "resto-core", "service": "resto-core", "state": "running", "status": "Up 2 hours (healthy)", "health": "healthy", "ports": ["8088->8080"], "image": "resto-core:local", "project": "resto"},
    {"name": "resto-n8n", "service": "n8n", "state": "running", "status": "Up 2 hours", "health": "", "ports": ["5678->5678"], "image": "n8n", "project": "resto"},
    {"name": "resto-metabase", "service": "metabase", "state": "exited", "status": "Exited (0) 3 minutes ago", "health": "", "ports": [], "image": "metabase", "project": "resto"},
]


def test_log_frames_are_unwrapped():
    frame = b"\x01\x00\x00\x00" + (5).to_bytes(4, "big") + b"hello"
    frame += b"\x02\x00\x00\x00" + (6).to_bytes(4, "big") + b" world"
    assert dockerctl._demux(frame) == "hello world"


def test_plain_log_bytes_survive():
    assert dockerctl._demux(b"no framing here") == "no framing here"


def test_health_word_is_read_from_the_status_line():
    assert dockerctl._health("Up 2 hours (healthy)") == "healthy"
    assert dockerctl._health("Up 5 seconds (health: starting)") == "starting"
    assert dockerctl._health("Up 2 hours") == ""


def test_names_match_the_way_people_text_them(monkeypatch):
    monkeypatch.setattr(dockerctl, "containers", lambda include_stopped=True: CONTAINERS)
    assert dockerctl.find_container("resto-n8n")["name"] == "resto-n8n"
    assert dockerctl.find_container("n8n")["name"] == "resto-n8n"
    assert dockerctl.find_container("metabase")["name"] == "resto-metabase"
    assert dockerctl.find_container("nothing-here") is None


def test_compose_runs_in_the_repo_with_every_file(monkeypatch):
    seen = {}

    def fake_run(cmd, timeout, cwd):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return {"ok": True, "code": 0, "output": ""}

    monkeypatch.setattr(dockerctl, "_run", fake_run)
    Path(settings.repo_dir, "compose.extra.yml").write_text("services: {}\n", encoding="utf-8")
    dockerctl.compose("up", "-d", "ntfy")
    assert seen["cwd"] == settings.repo_dir
    assert seen["cmd"][:2] == ["docker", "compose"]
    assert seen["cmd"].count("-f") == 2
    assert seen["cmd"][-3:] == ["up", "-d", "ntfy"]
    assert "--project-name" in seen["cmd"]


def test_compose_says_so_when_the_repo_is_not_mounted(monkeypatch):
    monkeypatch.setattr(settings, "repo_dir", "/nope")
    result = dockerctl.compose("ps")
    assert result["ok"] is False
    assert "REPO_DIR" in result["output"]


def test_missing_docker_binary_is_an_answer_not_a_crash(monkeypatch):
    def boom(*_args, **_kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(dockerctl.subprocess, "run", boom)
    result = dockerctl._run(["docker", "compose", "ps"], 10, settings.repo_dir)
    assert result["ok"] is False
    assert "not available" in result["output"]


def test_tail_keeps_the_end():
    assert dockerctl.tail("x" * 50, 10).endswith("x" * 10)
    assert dockerctl.tail("short", 10) == "short"
