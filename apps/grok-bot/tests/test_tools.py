from app import catalog, dockerctl, tools
from app.settings import settings

CONTAINERS = [
    {"name": "resto-core", "service": "resto-core", "state": "running", "status": "Up 2 hours (healthy)", "health": "healthy", "ports": ["8088->8080"], "image": "resto-core:local", "project": "resto"},
    {"name": "resto-n8n", "service": "n8n", "state": "exited", "status": "Exited (1) 4 minutes ago", "health": "", "ports": [], "image": "n8n", "project": "resto"},
]


def test_every_schema_matches_a_handler():
    named = {schema["function"]["name"] for schema in tools.SCHEMAS}
    assert named == set(tools.HANDLERS)


def test_only_server_changes_need_a_yes():
    assert tools.needs_confirm("restart_app") is True
    assert tools.needs_confirm("install_app") is True
    assert tools.needs_confirm("update_stack") is True
    assert tools.needs_confirm("server_status") is False
    assert tools.needs_confirm("restaurant_status") is False


def test_server_status_points_at_what_is_broken(monkeypatch):
    monkeypatch.setattr(dockerctl, "containers", lambda include_stopped=True: CONTAINERS)
    monkeypatch.setattr(dockerctl, "engine_info", lambda: {"running": 1, "docker_version": "27.0"})
    monkeypatch.setattr(dockerctl, "host_health", lambda: {"load": [0.4], "memory_used_pct": 41.0, "disk": {"used_pct": 62.0, "free_gb": 900.0}})
    result = tools.server_status()
    assert result["not_running"] == ["resto-n8n"]
    assert result["unhealthy"] == []


def test_a_dead_socket_is_reported_not_raised(monkeypatch):
    def boom(*_args, **_kwargs):
        raise dockerctl.DockerError("No Docker socket at /var/run/docker.sock")

    monkeypatch.setattr(dockerctl, "containers", boom)
    assert "No Docker socket" in tools.server_status()["error"]


def test_install_writes_compose_then_brings_the_app_up(monkeypatch):
    seen = []
    monkeypatch.setattr(dockerctl, "compose", lambda *args, **_kw: seen.append(args) or {"ok": True, "code": 0, "output": "Container resto-ntfy Started"})
    result = tools.install_app(app="ntfy")
    assert result["ok"] is True
    assert seen == [("up", "-d", "--no-deps", "ntfy")]
    assert catalog.installed() == ["ntfy"]


def test_a_failed_install_leaves_no_trace(monkeypatch):
    monkeypatch.setattr(dockerctl, "compose", lambda *_a, **_kw: {"ok": False, "code": 1, "output": "no such image"})
    result = tools.install_app(app="ntfy")
    assert "rolled the compose file back" in result["error"]
    assert catalog.installed() == []


def test_an_unknown_app_gets_the_catalog_back():
    result = tools.install_app(app="plex")
    assert "not in the catalog" in result["error"]
    assert "uptime-kuma" in result["error"]


def test_a_raw_image_is_allowed_when_the_setting_says_so(monkeypatch):
    monkeypatch.setattr(dockerctl, "compose", lambda *_a, **_kw: {"ok": True, "code": 0, "output": ""})
    result = tools.install_app(app="whoami", image="traefik/whoami:latest", port=8095)
    assert result["ok"] is True
    assert catalog.installed() == ["whoami"]


def test_raw_images_can_be_locked_down(monkeypatch):
    monkeypatch.setattr(settings, "allow_custom_images", False)
    result = tools.install_app(app="whoami", image="traefik/whoami:latest", port=8095)
    assert "turned off" in result["error"]


def test_a_port_the_stack_already_uses_is_refused():
    result = tools.install_app(app="whoami", image="traefik/whoami:latest", port=8088)
    assert "already published" in result["error"]


def test_remove_only_touches_what_the_bot_installed(monkeypatch):
    monkeypatch.setattr(dockerctl, "compose", lambda *_a, **_kw: {"ok": True, "code": 0, "output": ""})
    assert "will not remove" in tools.remove_app("postgres")["error"]
    tools.install_app(app="ntfy")
    assert tools.remove_app("ntfy")["ok"] is True
    assert catalog.installed() == []


def test_restart_reports_the_state_after(monkeypatch):
    monkeypatch.setattr(dockerctl, "containers", lambda include_stopped=True: CONTAINERS)
    monkeypatch.setattr(dockerctl, "lifecycle", lambda name, action: None)
    result = tools.restart_app("n8n")
    assert result["app"] == "resto-n8n"
    assert result["action"] == "restart"


def test_updating_one_app_leaves_its_dependencies_alone(monkeypatch):
    seen = []
    monkeypatch.setattr(dockerctl, "containers", lambda include_stopped=True: CONTAINERS)
    monkeypatch.setattr(dockerctl, "compose", lambda *args, **_kw: seen.append(args) or {"ok": True, "code": 0, "output": ""})
    tools.update_app("n8n")
    assert seen == [("pull", "n8n"), ("up", "-d", "--no-deps", "n8n")]


def test_update_stack_pulls_then_rebuilds(monkeypatch):
    seen = []
    monkeypatch.setattr(dockerctl, "git_pull", lambda: {"ok": True, "code": 0, "output": "Already up to date."})
    monkeypatch.setattr(dockerctl, "compose", lambda *args, **_kw: seen.append(args) or {"ok": True, "code": 0, "output": "10 containers started"})
    result = tools.update_stack()
    assert seen == [("up", "-d", "--build")]
    assert result["ok"] is True
    assert "Already up to date." in result["git"]


def test_bad_arguments_come_back_as_a_message():
    assert "Bad arguments" in tools.run("restart_app", {"container": "n8n"})["error"]
    assert "Unknown tool" in tools.run("drop_database", {})["error"]


def test_describe_reads_like_a_sentence():
    assert tools.describe("restart_app", {"app": "n8n"}) == "restart n8n"
    assert tools.describe("install_app", {"app": "ntfy"}) == "install ntfy"
    assert "whole stack" in tools.describe("update_stack", {})
