import json

import httpx

from app.hours import any_day_open, empty_hours, google_regular_hours
from app.menu_extract import parse_menu_text
from app.postiz import map_remote_state


def test_login_and_overview_have_no_invented_activity(owner):
    denied = owner.post("/api/logout")
    assert denied.status_code == 200
    blocked = owner.get("/api/overview")
    assert blocked.status_code == 401
    owner.post("/api/login", json={"email": "owner@survey.test", "password": "nope"})
    owner.post("/api/login", json={"email": "owner@survey.test", "password": "correct-horse"})
    overview = owner.get("/api/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["customer_activity"] is None
    assert body["ad_spend"] == []
    assert body["counts"]["posts_in_progress"] == 0
    statuses = {row["service"]: row for row in body["statuses"]}
    assert statuses["n8n"]["reachable"] is False
    assert statuses["dashboard database"]["reachable"] is True
    assert "resto-postgres" in statuses["dashboard database"]["detail"]


def test_yelp_push_stays_manual_and_google_confirms_only_on_success(owner, monkeypatch):
    yelp = owner.post("/api/profiles/yelp/push")
    assert yelp.status_code == 200
    assert yelp.json()["sync_state"] == "manual"
    assert yelp.json()["confirmed_at"] is None

    calls = {}

    class Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def patch(self, url, params=None, headers=None, json=None):
            calls["json"] = json
            calls["mask"] = params["updateMask"]
            status = calls.get("status", 403)
            return httpx.Response(status, json={"name": "locations/1", "error": {"message": "forbidden"}})

    monkeypatch.setattr("app.listings.httpx.Client", Dummy)
    owner.put(
        "/api/settings/secrets",
        json={"name": "google_access_token", "value": "token"},
    )
    owner.put("/api/settings/secrets", json={"name": "google_location_id", "value": "locations/99"})
    owner.put(
        "/api/profiles/google",
        json={
            "location_name": "Survey Café",
            "description": "Spanish kitchen",
            "phone": "",
            "website": "",
            "hours": empty_hours(),
            "holiday_hours": [],
            "announcement": "Paella night",
        },
    )
    rejected = owner.post("/api/profiles/google/push")
    assert rejected.status_code == 200
    assert rejected.json()["sync_state"] == "rejected"
    assert rejected.json()["confirmed_at"] is None
    assert "regularHours" not in calls["json"]
    assert "announcement" not in calls["json"]
    assert "title" in calls["mask"]

    calls["status"] = 200
    confirmed = owner.post("/api/profiles/google/push")
    assert confirmed.json()["sync_state"] == "confirmed"
    assert confirmed.json()["confirmed_at"]
    assert "Google accepted" in confirmed.json()["sync_detail"]
    assert "announcement" in confirmed.json()["sync_detail"].lower() or "Announcement" in confirmed.json()["sync_detail"]


def test_menu_parser_and_upload(owner):
    parsed = parse_menu_text("Paella Valenciana | saffron rice | 28\nGarlic shrimp - $16.50\nnot a price line\n")
    assert parsed[0]["name"] == "Paella Valenciana"
    assert parsed[0]["price_cents"] == 2800
    assert parsed[1]["price_cents"] == 1650
    assert len(parsed) == 2
    response = owner.post(
        "/api/menu/documents",
        files={"file": ("menu.txt", b"Tortilla | potato | 12\n", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "extracted"
    items = owner.get("/api/menu/items").json()["items"]
    assert items[0]["approved"] is False
    assert items[0]["price_cents"] == 1200
    approved = owner.patch(f"/api/menu/items/{items[0]['id']}", json={"approved": True, "category": "Tapas"})
    assert approved.json()["approved"] is True


def test_post_is_not_marked_published_without_postiz(owner, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("Postiz should not be called for Instagram without media")

    monkeypatch.setattr("app.postiz.request", explode)
    created = owner.post(
        "/api/posts",
        json={"body": "Tonight", "channels": [{"integration_id": "ig1", "provider": "instagram"}], "scheduled_for": ""},
    )
    refused = owner.post(f"/api/posts/{created.json()['id']}/submit?mode=now")
    assert refused.status_code == 409
    assert created.json()["status"] == "draft"

    monkeypatch.setattr(
        "app.postiz.request",
        lambda *args, **kwargs: __import__("app.remote", fromlist=["Remote"]).Remote(False, 0, None, "Postiz public API key is not saved"),
    )
    facebook = owner.post(
        "/api/posts",
        json={"body": "Hello", "channels": [{"integration_id": "fb1", "provider": "facebook"}], "scheduled_for": ""},
    )
    submitted = owner.post(f"/api/posts/{facebook.json()['id']}/submit?mode=now")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "draft"
    assert submitted.json()["release_url"] == ""
    assert "API key" in submitted.json()["detail"]
    assert map_remote_state("QUEUE") == "submitted"
    assert map_remote_state("PUBLISHED") == "published"


def test_review_reply_requires_support_and_approval(owner, monkeypatch):
    yelp = owner.post(
        "/api/reviews",
        json={"platform": "yelp", "author": "Sam", "rating": 4, "body": "Lovely rice", "reviewed_at": ""},
    ).json()
    owner.post(f"/api/reviews/{yelp['id']}/draft")
    owner.post(f"/api/reviews/{yelp['id']}/approval", json={"approval": "approved"})
    sent = owner.post(f"/api/reviews/{yelp['id']}/send")
    assert sent.json()["publish_state"] == "unavailable"
    assert sent.json()["draft_source"] == "template"

    def boom(*args, **kwargs):
        raise AssertionError("Google should not be called before approval")

    monkeypatch.setattr("app.listings.reply_google_review", boom)
    google = owner.post(
        "/api/reviews",
        json={
            "platform": "google",
            "author": "Ana",
            "rating": 5,
            "body": "Great paella",
            "reviewed_at": "",
        },
    ).json()
    early = owner.post(f"/api/reviews/{google['id']}/send")
    assert early.status_code == 409


def test_event_queue_does_not_publish_and_n8n_key_is_required(owner):
    event = owner.post(
        "/api/events",
        json={"name": "Paella Night", "kind": "dinner", "starts_at": "2026-12-01T18:00:00", "description": "Two seatings"},
    ).json()
    queued = owner.post(f"/api/events/{event['id']}/queue")
    assert queued.json()["published"] is False
    assert queued.json()["post"]["status"] == "draft"
    assert queued.json()["campaign"]["status"] == "local"
    anon = owner.post("/api/logout")
    assert anon.status_code == 200
    missing = owner.post("/api/n8n/events/announce", json={"name": "Private dinner", "starts_at": "2026-12-02T19:00:00"})
    assert missing.status_code == 401
    announced = owner.post(
        "/api/n8n/events/announce",
        headers={"X-API-Key": "test-api-key"},
        json={"name": "Private dinner", "starts_at": "2026-12-02T19:00:00", "description": "Buyout"},
    )
    assert announced.status_code == 200
    assert announced.json()["published"] is False


def test_export_leaves_secrets_out(owner):
    owner.put("/api/settings/secrets", json={"name": "mautic_password", "value": "super-secret-value"})
    exported = json.dumps(owner.get("/api/admin/export").json())
    assert "super-secret-value" not in exported
    assert "secrets_included" in exported
    settings = owner.get("/api/settings").json()
    password = next(field for field in settings["fields"] if field["name"] == "mautic_password")
    assert password["configured"] is True
    assert password["value"] == ""


def test_closed_week_is_not_a_google_hours_payload():
    assert google_regular_hours(empty_hours()) is None
    assert any_day_open(empty_hours()) is False


def test_marketing_compose_is_pinned_and_isolated():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, str(root / "scripts/check-marketing-compose.py")], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    main = (root / "compose.yml").read_text(encoding="utf-8")
    assert "mautic/mautic" not in main
    assert "postiz-app" not in main


def test_integrations_are_not_marked_live(owner):
    body = owner.get("/api/integrations").json()
    assert body["live_calls_made"] is False
    rows = {row["id"]: row for row in body["integrations"]}
    assert rows["google"]["verification"] == "unit_test"
    assert rows["google"]["live_verified"] is False
    assert rows["apple"]["code"] == "not_implemented"
    assert rows["postiz"]["verification"] == "unit_test"
    assert rows["mautic"]["verification"] == "not_run_live"
    assert all(row["live_verified"] is False for row in body["integrations"])
    assert all(row["authorized_api_test"] is False for row in body["integrations"])


def test_storage_and_resource_guards():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts" / "preflight_marketing.py"
    spec = importlib.util.spec_from_file_location("preflight_marketing", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _notes, errors = module.assess_storage("/mnt/disk1/appdata/resto", None, True)
    assert errors
    only = 'shareUseCache="only"\nshareCachePool="nvme"\n'
    notes, errors = module.assess_storage("/mnt/user/appdata/resto", only, True, transports={"nvme": {"nvme"}})
    assert errors == []
    assert any("NVMe" in note for note in notes)
    notes, errors = module.assess_storage(
        "/mnt/user/appdata/resto",
        'shareUseCache="yes"\nshareCachePool="nvme"\n',
        True,
        transports={"nvme": {"nvme"}},
    )
    assert any("array" in item for item in errors)
    notes, errors = module.assess_storage(
        "/mnt/user/appdata/resto",
        'shareUseCache="only"\nshareCachePool="cache"\nshareCachePool2="cache2"\n',
        True,
        transports={"cache": {"nvme"}},
    )
    assert any("cache2" in item for item in errors)
    notes, errors = module.assess_zfs(
        [{"name": "cache/appdata", "mountpoint": "/mnt/cache/appdata", "recordsize": "128K", "compression": "lz4", "sync": "standard", "logbias": "latency", "primarycache": "all", "atime": "on"}],
        "/mnt/cache/appdata/resto",
    )
    assert notes and errors == []
    assert any("left as it is" in note for note in notes)
    assert any("does not run zfs" in note for note in notes)
    _, resource_errors = module.assess_resources(2 * 1024 * 1024, 20.0, 4)
    assert any("GiB" in item for item in resource_errors)
    join_notes, join_errors = module.assess_networks(
        [{"name": "resto", "driver": "bridge", "subnets": ["172.20.0.0/16"], "used": 12, "attached": ["resto-n8n"]}],
        None,
        ["192.168.1.0/24"],
    )
    assert join_errors == []
    assert any("joins the existing resto network" in note for note in join_notes)
    _notes, tight_errors = module.assess_networks(
        [{"name": "resto", "driver": "bridge", "subnets": ["172.20.0.0/28"], "used": 10, "attached": []}],
        None,
        [],
    )
    assert any("free addresses" in item for item in tight_errors)
    _notes, overlap_errors = module.assess_networks(
        [
            {"name": "resto", "driver": "bridge", "subnets": ["172.20.0.0/16"], "used": 1, "attached": []},
            {"name": "other", "driver": "bridge", "subnets": ["172.20.1.0/24"], "used": 1, "attached": []},
        ],
        None,
        [],
    )
    assert any("overlap" in item for item in overlap_errors)
    create_notes, create_errors = module.assess_networks(
        [{"name": "bridge", "driver": "bridge", "subnets": ["172.17.0.0/16"], "used": 1, "attached": []}],
        [("172.30.0.0/24", 24), ("172.30.1.0/24", 24)],
        ["172.30.0.0/24"],
    )
    assert create_errors == []
    assert any("172.30.1.0/24" in note for note in create_notes)
    _notes, full_errors = module.assess_networks(
        [{"name": "bridge", "driver": "bridge", "subnets": ["172.30.0.0/24"], "used": 1, "attached": []}],
        [("172.30.0.0/24", 24)],
        [],
    )
    assert any("No free IPv4 subnet" in item for item in full_errors)
    assert module.assess_map_count(65530, "postiz")
    assert module.assess_map_count(65530, "mautic") is None
    _notes, bind_errors = module.assess_bind("100.116.48.120", ["100.116.48.120"], True)
    assert bind_errors == []
    _notes, bind_errors = module.assess_bind("127.0.0.1", ["127.0.0.1"], True)
    assert bind_errors
    _notes, bind_errors = module.assess_bind("192.168.1.20", ["192.168.1.20"], True)
    assert bind_errors


def test_unraid_inspect_script_is_read_only():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "scripts" / "inspect-unraid-readonly.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#") and "echo " not in line)
    for banned in ("git checkout", "git pull", "git reset", "docker run", "docker network create", "compose up", "zfs set", "zfs create", "sysctl"):
        assert banned not in code
    assert "/tmp/unraid-marketing-inspect.txt" in text
    assert "git -C" in text
    assert "bash <<'UNRAID_INSPECT'" in text
    assert text.strip().endswith("UNRAID_INSPECT")
    assert "export GIT_OPTIONAL_LOCKS=0" in text
    assert "docker network inspect $ids --format" in text
    assert "sed -n '1,200p' /etc/docker/daemon.json" not in text
    assert "git diff\n" not in text
    assert "git diff --cached\n" not in text


def test_marketing_stages_do_not_start_without_approval():
    import os
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    dry = subprocess.run(["bash", str(root / "scripts/up-marketing.sh"), "--dry-run"], cwd=root, capture_output=True, text=True)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "mautic" in dry.stdout
    assert "postiz" in dry.stdout
    assert "dashboard" in dry.stdout
    refused = subprocess.run(["bash", str(root / "scripts/up-marketing.sh"), "--stage", "mautic"], cwd=root, capture_output=True, text=True)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "Nothing was started" in refused.stdout
    stage = subprocess.run(
        ["bash", str(root / "scripts/up-marketing.sh"), "--stage", "postiz", "--dry-run"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert stage.returncode == 0, stage.stdout + stage.stderr
    services = stage.stdout.split("Stage postiz creates or starts only:", 1)[1].split("\n\n", 1)[0]
    assert "temporal-elasticsearch" in services
    assert "\n  command\n" not in services


def test_rollback_removes_only_marketing_containers(tmp_path):
    import os
    import stat
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "ps" ]; then\n'
        "  printf '%s\\n' mealie paperless-ngx-webserver-1 resto-mautic resto-postgres\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "inspect" ] && [ "$2" = "-f" ]; then\n'
        '  case "$4" in\n'
        '    resto-postgres) echo "/resto-postgres id-pg running" ;;\n'
        '    mealie) echo "/mealie id-mealie running" ;;\n'
        '    paperless-ngx-webserver-1) echo "/paperless-ngx-webserver-1 id-paper running" ;;\n'
        "    *) exit 1 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "inspect" ]; then\n'
        '  case "$2" in\n'
        "    resto-mautic|resto-postgres|mealie|paperless-ngx-webserver-1) exit 0 ;;\n"
        "  esac\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["MARKETING_ROLLBACK_APPROVED"] = "1"
    env["MARKETING_ROLLBACK_DELETE_DATA"] = "0"
    env["APPDATA"] = str(tmp_path / "appdata")
    result = subprocess.run(
        ["bash", str(root / "scripts/rollback-marketing.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = log.read_text(encoding="utf-8")
    assert "rm -f resto-mautic\n" in text
    assert "rm -f resto-postgres" not in text
    assert "rm -f resto-n8n" not in text
    assert "rm -f mealie" not in text
    assert "rm -f paperless-ngx-webserver-1" not in text
    assert "inspect -f {{.Name}} {{.Id}} {{.State.Status}} mealie" in text
    assert "Containers outside the marketing list were not removed." in result.stdout


def test_marketing_paths_and_postiz_gate():
    import os
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    refused = subprocess.run(
        ["bash", "-c", "source scripts/marketing-guard.sh; marketing_refuse_production /mnt/cache/appdata/resto/n8n"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "production resto tree" in refused.stdout
    postiz = subprocess.run(
        ["bash", str(root / "scripts/up-marketing.sh"), "--stage", "postiz"],
        cwd=root,
        env={**os.environ, "MARKETING_APPROVED": "1"},
        capture_output=True,
        text=True,
    )
    assert postiz.returncode == 3, postiz.stdout + postiz.stderr
    assert "Postiz stays stopped" in postiz.stdout
    clone = subprocess.run(
        ["bash", str(root / "scripts/clone-marketing-source.sh")],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert clone.returncode == 3, clone.stdout + clone.stderr
    blocked = subprocess.run(
        ["bash", str(root / "scripts/clone-marketing-source.sh")],
        cwd=root,
        env={**os.environ, "MARKETING_CLONE_APPROVED": "1", "MARKETING_SOURCE": "/mnt/user/appdata/resto"},
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    py = subprocess.run(["bash", str(root / "scripts/ensure-private-python.sh")], cwd=root, capture_output=True, text=True)
    assert py.returncode == 0, py.stdout + py.stderr
    assert py.stdout.strip().endswith("python3")


def test_fresh_env_example_sources_and_mautic_preflight_can_finish(tmp_path, monkeypatch, capsys):
    import importlib.util
    import os
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    first = subprocess.run(["bash", str(root / "scripts/check-marketing-firstrun.sh")], cwd=root, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Sourced a fresh .env.example in an isolated shell." in first.stdout
    assert "Compose config validated for the Mautic service. No container was started." in first.stdout
    assert "docker compose up" not in (root / "scripts/check-marketing-firstrun.sh").read_text(encoding="utf-8")
    assert not Path("/mnt/cache/appdata/surveycafe-marketing").exists()
    assert "already existed" not in first.stdout

    broken = tmp_path / "unquoted.env"
    broken.write_text(
        (root / ".env.example").read_text(encoding="utf-8").replace(
            'HOME_MARKET="Bonita Springs, Florida"',
            "HOME_MARKET=Bonita Springs, Florida",
        ),
        encoding="utf-8",
    )
    unquoted = subprocess.run(
        [
            "env",
            "-i",
            f"PATH={os.environ['PATH']}",
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'set -euo pipefail; set -a; source "$1"; set +a',
            "bash",
            str(broken),
        ],
        capture_output=True,
        text=True,
    )
    assert unquoted.returncode != 0, unquoted.stdout + unquoted.stderr

    fresh = tmp_path / "fresh.env"
    fresh.write_text((root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    dumped = subprocess.run(
        [
            "env",
            "-i",
            f"PATH={os.environ['PATH']}",
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'set -euo pipefail; set -a; source "$1"; set +a; printf "%s\\n" "$HOME_MARKET" "$APPDATA" "$BIND_ADDR" "$HOME_LON" "$COMMAND_ADMIN_EMAIL"',
            "bash",
            str(fresh),
        ],
        capture_output=True,
        text=True,
    )
    assert dumped.returncode == 0, dumped.stdout + dumped.stderr
    market, appdata, bind, lon, email = dumped.stdout.splitlines()
    assert market == "Bonita Springs, Florida"
    assert appdata == "/mnt/cache/appdata/surveycafe-marketing"
    assert bind == "100.116.48.120"
    assert lon == "-81.7787"
    assert email == "surveycafedowntown@gmail.com"
    monkeypatch.setenv("APPDATA", appdata)
    monkeypatch.setenv("BIND_ADDR", bind)

    hosted = subprocess.run(
        ["bash", str(root / "scripts/preflight-marketing.sh")],
        cwd=root,
        env={**os.environ, "MARKETING_ENV_FILE": str(fresh), "MARKETING_STAGE": "mautic"},
        capture_output=True,
        text=True,
    )
    assert hosted.returncode in {0, 2}, hosted.stdout + hosted.stderr
    assert "Read-only preflight" in hosted.stdout
    assert "command not found" not in hosted.stderr
    assert "Springs" not in hosted.stderr

    path = root / "scripts" / "preflight_marketing.py"
    spec = importlib.util.spec_from_file_location("preflight_marketing_firstrun", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_mem_available", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(module, "_load", lambda: 0.4)
    monkeypatch.setattr(module, "_cpus", lambda: 8)
    monkeypatch.setattr(module, "_map_count", lambda: 65530)
    monkeypatch.setattr(module, "_local_ipv4", lambda: ["100.116.48.120"])
    monkeypatch.setattr(
        module,
        "_docker_networks",
        lambda: (
            [{"name": "resto", "driver": "bridge", "subnets": ["172.29.0.0/16"], "used": 8, "attached": ["mealie", "resto-n8n"]}],
            {},
            [],
        ),
    )
    monkeypatch.setattr(module, "_address_pools", lambda: None)
    monkeypatch.setattr(module, "_nondocker_routes", lambda: ["192.168.1.0/24"])
    monkeypatch.setattr(module, "_zfs_rows", lambda: [])
    monkeypatch.setenv("MARKETING_STAGE", "mautic")
    assert module.main() == 0
    mautic_out = capsys.readouterr().out
    assert "Preflight finished" in mautic_out
    assert "Mautic stage does not start Elasticsearch" in mautic_out
    monkeypatch.setenv("MARKETING_STAGE", "postiz")
    assert module.main() == 2
    postiz_out = capsys.readouterr().out
    assert "vm.max_map_count is 65530" in postiz_out

    dashboard = subprocess.run(
        ["bash", str(root / "scripts/up-marketing.sh"), "--stage", "dashboard"],
        cwd=root,
        env={**os.environ, "MARKETING_APPROVED": "1"},
        capture_output=True,
        text=True,
    )
    assert dashboard.returncode == 3, dashboard.stdout + dashboard.stderr
    assert "dashboard stays stopped" in dashboard.stdout
    public = subprocess.run(["bash", str(root / "scripts/up-public-edge.sh")], cwd=root, capture_output=True, text=True)
    assert public.returncode == 3, public.stdout + public.stderr
    assert "Public HTTPS" in public.stdout


def test_marketing_env_backup_round_trip(tmp_path):
    import os
    import stat
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    secret = "mautic-db-pass-test-value-9f3c"
    root_pass = "mautic-root-pass-test-value-9f3c"
    command_key = "command-secret-key-test-value-9f3c"
    admin = "correct horse battery"
    passphrase = "test-passphrase-sixteen"
    env_file = tmp_path / "checkout" / ".env"
    env_file.parent.mkdir()
    data = tmp_path / "surveycafe-marketing"
    backup_root = tmp_path / "backups"
    env_file.write_text(
        "\n".join(
            [
                f"APPDATA={data}",
                'HOME_MARKET="Bonita Springs, Florida"',
                f"MAUTIC_DB_PASSWORD={secret}",
                f"MAUTIC_DB_ROOT_PASSWORD={root_pass}",
                f"COMMAND_SECRET_KEY={command_key}",
                f'COMMAND_ADMIN_PASSWORD="{admin}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o644)
    original = env_file.read_bytes()
    base = os.environ.copy()
    base.update(
        {
            "MARKETING_ENV_FILE": str(env_file),
            "MARKETING_ENV_BACKUP_DIR": str(backup_root),
            "MARKETING_ENV_PASSPHRASE": passphrase,
        }
    )

    def run(script, env, args=None):
        return subprocess.run(
            ["bash", str(root / "scripts" / script), *(args or [])],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )

    refused = run("backup-marketing-env.sh", {**base, "MARKETING_ENV_BACKUP_APPROVED": "0"})
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert secret not in refused.stdout
    assert passphrase not in refused.stdout
    assert not backup_root.exists()

    short = run(
        "backup-marketing-env.sh",
        {**base, "MARKETING_ENV_BACKUP_APPROVED": "1", "MARKETING_ENV_PASSPHRASE": "too-short"},
    )
    assert short.returncode == 1, short.stdout + short.stderr
    assert not backup_root.exists()

    inside_source = run(
        "backup-marketing-env.sh",
        {**base, "MARKETING_ENV_BACKUP_APPROVED": "1", "MARKETING_ENV_BACKUP_DIR": str(root / "not-a-backup")},
    )
    assert inside_source.returncode == 1, inside_source.stdout + inside_source.stderr
    assert "source checkout" in inside_source.stdout
    assert not (root / "not-a-backup").exists()

    inside_data = run(
        "backup-marketing-env.sh",
        {**base, "MARKETING_ENV_BACKUP_APPROVED": "1", "MARKETING_ENV_BACKUP_DIR": str(data / "nested")},
    )
    assert inside_data.returncode == 1, inside_data.stdout + inside_data.stderr
    assert "APPDATA" in inside_data.stdout

    production = run(
        "backup-marketing-env.sh",
        {
            **base,
            "MARKETING_ENV_BACKUP_APPROVED": "1",
            "MARKETING_ENV_FILE": "/mnt/cache/appdata/resto/.env",
        },
    )
    assert production.returncode == 1, production.stdout + production.stderr
    assert "production resto tree" in production.stdout

    saved = run("backup-marketing-env.sh", {**base, "MARKETING_ENV_BACKUP_APPROVED": "1"})
    assert saved.returncode == 0, saved.stdout + saved.stderr
    combined = saved.stdout + saved.stderr
    assert secret not in combined
    assert root_pass not in combined
    assert command_key not in combined
    assert passphrase not in combined
    assert admin not in combined
    assert "Encrypted marketing .env:" in saved.stdout
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    enc = next(backup_root.glob("*/marketing.env.enc"))
    blob = enc.read_bytes()
    assert secret.encode() not in blob
    assert passphrase.encode() not in blob
    assert admin.encode() not in blob
    assert stat.S_IMODE(enc.stat().st_mode) == 0o600
    readme = (enc.parent / "README.txt").read_text(encoding="utf-8")
    assert secret not in readme
    assert passphrase not in readme
    assert not str(enc).startswith(str(root))

    restored = tmp_path / "restored.env"
    restore_env = {**base, "MARKETING_ENV_FILE": str(restored), "MARKETING_ENV_RESTORE_APPROVED": "1"}
    blocked = run("restore-marketing-env.sh", {**restore_env, "MARKETING_ENV_RESTORE_APPROVED": "0"}, [str(enc.parent)])
    assert blocked.returncode == 3, blocked.stdout + blocked.stderr
    assert not restored.exists()

    wrong = run(
        "restore-marketing-env.sh",
        {**restore_env, "MARKETING_ENV_PASSPHRASE": "wrong-passphrase-value"},
        [str(enc.parent)],
    )
    assert wrong.returncode == 1, wrong.stdout + wrong.stderr
    assert not restored.exists()
    assert secret not in wrong.stdout

    checksum = enc.parent / "marketing.env.enc.sha256"
    checksum_text = checksum.read_text(encoding="utf-8")
    checksum.write_text("0" * 64 + "\n", encoding="utf-8")
    damaged = run("restore-marketing-env.sh", restore_env, [str(enc.parent)])
    assert damaged.returncode == 1, damaged.stdout + damaged.stderr
    assert "checksum" in damaged.stdout
    assert not restored.exists()
    checksum.write_text(checksum_text, encoding="utf-8")

    good = run("restore-marketing-env.sh", restore_env, [str(enc.parent)])
    assert good.returncode == 0, good.stdout + good.stderr
    assert secret not in good.stdout
    assert passphrase not in good.stdout
    assert restored.read_bytes() == original
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600

    restored.write_text(restored.read_text(encoding="utf-8").replace(secret, "changed-password-value-xx"), encoding="utf-8")
    kept = run("restore-marketing-env.sh", restore_env, [str(enc.parent)])
    assert kept.returncode == 1, kept.stdout + kept.stderr
    assert "changed-password-value-xx" in restored.read_text(encoding="utf-8")

    replaced = run(
        "restore-marketing-env.sh",
        {**restore_env, "MARKETING_ENV_RESTORE_OVERWRITE": "1"},
        [str(enc.parent)],
    )
    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    assert restored.read_bytes() == original
    assert secret not in replaced.stdout

    inside_appdata = data / ".env"
    nested = run(
        "restore-marketing-env.sh",
        {**restore_env, "MARKETING_ENV_FILE": str(inside_appdata), "MARKETING_ENV_RESTORE_OVERWRITE": "1"},
        [str(enc.parent)],
    )
    assert nested.returncode == 1, nested.stdout + nested.stderr
    assert "APPDATA" in nested.stdout
    assert not inside_appdata.exists()

    prod_restore = run(
        "restore-marketing-env.sh",
        {**restore_env, "MARKETING_ENV_FILE": "/mnt/cache/appdata/resto/.env", "MARKETING_ENV_RESTORE_OVERWRITE": "1"},
        [str(enc.parent)],
    )
    assert prod_restore.returncode == 1, prod_restore.stdout + prod_restore.stderr
    assert "production resto tree" in prod_restore.stdout
    assert not Path("/mnt/cache/appdata/resto/.env").exists()


def test_firstrun_checker_reruns_when_marketing_data_exists():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    data = Path("/mnt/cache/appdata/surveycafe-marketing")
    created = False
    if not data.exists():
        subprocess.run(["sudo", "mkdir", "-p", str(data / "mautic" / "config")], check=True)
        created = True
    try:
        result = subprocess.run(
            ["bash", str(root / "scripts/check-marketing-firstrun.sh")],
            cwd=root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Marketing data directory already existed. Compose config did not add directories." in result.stdout
        assert "No container was started." in result.stdout
        assert data.is_dir()
    finally:
        if created:
            subprocess.run(["sudo", "rm", "-rf", str(data)], check=True)


def test_mautic_phase1_stops_when_preflight_fails(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/deploy-mautic-phase1.sh"
    text = script.read_text(encoding="utf-8")
    assert "d82e03f39aaa74d34c59ea009d7a4b8fb15a170a" in text
    assert "--stage mautic" in text
    assert "--stage postiz" not in text
    assert "docker network create" not in text
    assert "sysctl" not in text
    assert "vm.max_map_count" not in text
    held = subprocess.run(["bash", str(script)], cwd=root, capture_output=True, text=True)
    assert held.returncode == 3, held.stdout + held.stderr
    assert "Nothing was started." in held.stdout
    env = os.environ.copy()
    env["MARKETING_PHASE1_APPROVED"] = "1"
    env.pop("MARKETING_MEMORY_ACK", None)
    env.pop("MARKETING_LOAD_ACK", None)
    refused = subprocess.run(["bash", str(script)], cwd=root, env=env, capture_output=True, text=True)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "Preflight failed. No container was started." in refused.stdout
    assert "No marketing .env was installed." in refused.stdout
    assert not (root / ".env").exists()
    assert "Approved Mautic commit d82e03f39aaa74d34c59ea009d7a4b8fb15a170a is contained" in refused.stdout
