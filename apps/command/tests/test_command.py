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
    assert body["engagement"] is None
    assert body["ad_spend"] == []
    assert body["counts"]["posts_in_progress"] == 0
    assert body["counts"]["posts_published"] == 0
    assert body["scheduled_posts"] == []
    assert body["failed_posts"] == []
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
    assert body["functional_from_unit_tests"] is False
    runtime = {row["id"]: row for row in body["runtime"]}
    assert runtime["mautic"]["configured"] is False
    assert runtime["mautic"]["genuinely_tested"] is False
    assert runtime["postiz"]["authorized"] is None
    assert runtime["google_ads"]["reachable"] is None
    assert all(row["genuinely_tested"] is False for row in body["runtime"])


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
    assert "MAUTIC_TRUSTED_PROXIES is []." in first.stdout
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
    assert text.index('"$ROOT/scripts/ensure-private-python.sh"') < text.index('"$ROOT/scripts/check-marketing-firstrun.sh"')
    assert text.index('"$ROOT/scripts/ensure-private-python.sh"') < text.index('"$ROOT/scripts/preflight-marketing.sh"')
    clone = (root / "scripts/clone-marketing-source.sh").read_text(encoding="utf-8")
    assert 'checkout --detach "$deploy_commit"' in clone
    assert 'checkout --detach "origin/${branch}"' not in clone
    assert "sysctl" not in text
    assert "vm.max_map_count" not in text
    held = subprocess.run(["bash", str(script)], cwd=root, capture_output=True, text=True)
    assert held.returncode == 3, held.stdout + held.stderr
    assert "Nothing was started." in held.stdout
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    env = os.environ.copy()
    env["MARKETING_PHASE1_APPROVED"] = "1"
    env["MARKETING_DEPLOY_COMMIT"] = head
    env.pop("MARKETING_MEMORY_ACK", None)
    env.pop("MARKETING_LOAD_ACK", None)
    env.pop("MARKETING_ENV_PASSPHRASE", None)
    refused = subprocess.run(["bash", str(script)], cwd=root, env=env, capture_output=True, text=True)
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "Preflight failed. No container was started." in refused.stdout
    assert "No marketing .env was installed." in refused.stdout
    assert "resto-mautic status=absent" in refused.stdout
    assert not (root / ".env").exists()
    assert "Approved Mautic commit d82e03f39aaa74d34c59ea009d7a4b8fb15a170a is contained" in refused.stdout
    assert "Reviewed installer commit e8f918406dd0b004e5d1c4ee64d4654ba4e03939 is contained" in refused.stdout

    wrong = env.copy()
    wrong["MARKETING_DEPLOY_COMMIT"] = "0123456789abcdef0123456789abcdef01234567"
    mismatched = subprocess.run(["bash", str(script)], cwd=root, env=wrong, capture_output=True, text=True)
    assert mismatched.returncode == 1, mismatched.stdout + mismatched.stderr
    assert "pinned deployment commit" in mismatched.stdout
    assert not (root / ".env").exists()

    branch = env.copy()
    branch["MARKETING_DEPLOY_COMMIT"] = "cursor/marketing-deploy-safety-7375"
    named = subprocess.run(["bash", str(script)], cwd=root, env=branch, capture_output=True, text=True)
    assert named.returncode == 1, named.stdout + named.stderr
    assert "branch name is not accepted" in named.stdout

    short_pass = "short-pass"
    rejected = env.copy()
    rejected["MARKETING_ENV_PASSPHRASE"] = short_pass
    bad_pass = subprocess.run(["bash", str(script)], cwd=root, env=rejected, capture_output=True, text=True)
    assert bad_pass.returncode == 6, bad_pass.stdout + bad_pass.stderr
    assert "passphrase was rejected" in bad_pass.stdout
    assert short_pass not in bad_pass.stdout + bad_pass.stderr
    assert not (root / ".env").exists()


def test_phase1_uses_private_python_when_the_host_has_none(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    wt = tmp_path / "checkout"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], cwd=root, check=True)
    try:
        for name in ("deploy-mautic-phase1.sh", "ensure-private-python.sh"):
            shutil.copy(root / "scripts" / name, wt / "scripts" / name)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        seen = set()
        for directory in os.environ["PATH"].split(os.pathsep):
            folder = Path(directory)
            if not folder.is_dir():
                continue
            for entry in folder.iterdir():
                if entry.name.startswith("python") or entry.name in seen:
                    continue
                if entry.is_file() and os.access(entry, os.X_OK):
                    os.symlink(entry, bindir / entry.name)
                    seen.add(entry.name)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, check=True, capture_output=True, text=True).stdout.strip()
        env = os.environ.copy()
        env["PATH"] = str(bindir)
        env["MARKETING_PHASE1_APPROVED"] = "1"
        env["MARKETING_DEPLOY_COMMIT"] = head
        env.pop("MARKETING_ENV_PASSPHRASE", None)
        env.pop("MARKETING_PYTHON_FETCH", None)
        result = subprocess.run(
            ["bash", str(wt / "scripts/deploy-mautic-phase1.sh")],
            cwd=wt,
            env=env,
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        private = wt / ".tools" / "python" / "bin" / "python3"
        assert result.returncode == 2, combined
        assert private.is_file()
        assert ".tools/python/bin/python3" in result.stdout
        assert "Using the private CPython under .tools. No system package was installed." in result.stdout
        assert "Sourced a fresh .env.example in an isolated shell." in result.stdout
        assert "Preflight failed. No container was started." in result.stdout
        assert "Host python3 is missing" not in combined
        assert not (wt / ".env").exists()
        version = subprocess.run(
            [str(private), "-c", "import sys; print(sys.version_info[:2])"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert version.stdout.strip() == "(3, 12)"
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=root, check=False)


def test_trusted_proxies_json_is_corrected_without_touching_other_secrets(tmp_path):
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "fix-mautic-trusted-proxies.py"
    secret = "mautic-db-pass-test-value-9f3c"
    broken = tmp_path / "broken.env"
    broken.write_text(
        f"MAUTIC_DB_PASSWORD={secret}\nMAUTIC_TRUSTED_PROXIES=172.16.0.0/12\n",
        encoding="utf-8",
    )
    checked = subprocess.run(["python3", str(script), "--check", str(broken)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert checked.stdout.strip() == "invalid"
    assert broken.read_text(encoding="utf-8") == f"MAUTIC_DB_PASSWORD={secret}\nMAUTIC_TRUSTED_PROXIES=172.16.0.0/12\n"
    result = subprocess.run(["python3", str(script), str(broken)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "corrected"
    text = broken.read_text(encoding="utf-8")
    assert f"MAUTIC_DB_PASSWORD={secret}" in text
    assert "MAUTIC_TRUSTED_PROXIES='[]'" in text
    assert "172.16.0.0/12" not in text
    assert secret not in result.stdout + result.stderr

    kept = tmp_path / "kept.env"
    original = "MAUTIC_TRUSTED_PROXIES='[\"172.29.0.0/16\"]'\nMAUTIC_DB_PASSWORD=already-set\n"
    kept.write_text(original, encoding="utf-8")
    checked_kept = subprocess.run(["python3", str(script), "--check", str(kept)], capture_output=True, text=True)
    assert checked_kept.returncode == 0, checked_kept.stdout + checked_kept.stderr
    assert checked_kept.stdout.strip() == "valid"
    assert kept.read_text(encoding="utf-8") == original
    again = subprocess.run(["python3", str(script), str(kept)], capture_output=True, text=True)
    assert again.returncode == 0, again.stdout + again.stderr
    assert again.stdout.strip() == "kept"
    assert kept.read_text(encoding="utf-8") == original


def test_map_count_script_changes_nothing_until_approved():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    before = Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8")
    env = {key: value for key, value in __import__("os").environ.items() if key != "MARKETING_MAP_COUNT_APPROVED"}
    result = subprocess.run(["bash", str(root / "scripts" / "map-count-unraid.sh")], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "Nothing was changed." in result.stdout
    assert "map-count-rollback.sh" in result.stdout
    assert Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8") == before


def test_phase2_stops_before_docker_and_preserves_mautic_rollback():
    import os
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "deploy-postiz-phase2.sh"
    text = script.read_text(encoding="utf-8")
    assert "sysctl -w" not in text
    assert "docker network create" not in text
    assert "--stage mautic" not in text
    assert text.index('phase2-${stamp}-before') < text.index("--check")
    assert text.index("--check") < text.index("fill_marketing_secrets")
    assert "--stage postiz" in text
    assert "MARKETING_DASHBOARD_APPROVED" in text
    assert "MARKETING_PUBLIC_APPROVED" in text
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()

    refused = subprocess.run(["bash", str(script)], cwd=root, capture_output=True, text=True)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "Nothing was started." in refused.stdout

    env = os.environ.copy()
    env["MARKETING_PHASE2_APPROVED"] = "1"
    env["MARKETING_DEPLOY_COMMIT"] = "cursor/postiz-phase2-7375"
    env.pop("MARKETING_ENV_PASSPHRASE", None)
    named = subprocess.run(["bash", str(script)], cwd=root, env=env, capture_output=True, text=True)
    assert named.returncode == 1, named.stdout + named.stderr
    assert "branch name is not accepted" in named.stdout

    passphrase = "phase2-passphrase-token"
    short = env.copy()
    short["MARKETING_DEPLOY_COMMIT"] = head
    short["MARKETING_ENV_PASSPHRASE"] = "short-pass"
    bad = subprocess.run(["bash", str(script)], cwd=root, env=short, capture_output=True, text=True)
    assert bad.returncode == 6, bad.stdout + bad.stderr
    assert "passphrase was rejected" in bad.stdout
    assert "short-pass" not in bad.stdout + bad.stderr
    assert not (root / ".env").exists()

    missing = env.copy()
    missing["MARKETING_DEPLOY_COMMIT"] = head
    missing["MARKETING_ENV_PASSPHRASE"] = passphrase
    stopped = subprocess.run(["bash", str(script)], cwd=root, env=missing, capture_output=True, text=True)
    assert stopped.returncode == 1, stopped.stdout + stopped.stderr
    assert "working marketing .env must already exist" in stopped.stdout
    assert passphrase not in stopped.stdout + stopped.stderr
    assert "Phase 2 does not copy .env.example" in stopped.stdout
    assert not (root / ".env").exists()

    rollback = subprocess.run(["bash", str(root / "scripts" / "rollback-postiz-phase2.sh")], cwd=root, capture_output=True, text=True)
    assert rollback.returncode == 3, rollback.stdout + rollback.stderr
    assert "resto-mautic" in rollback.stdout
    assert "Nothing was stopped." in rollback.stdout


def test_phase2_rollback_removes_postiz_and_leaves_mautic(tmp_path):
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
        "  printf '%s\\n' mealie resto-mautic resto-postiz resto-temporal resto-postgres\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "inspect" ] && [ "$2" = "-f" ]; then\n'
        '  case "$4" in\n'
        '    resto-mautic|resto-mautic-mysql|resto-mautic-cron|resto-mautic-worker) echo "id-mautic" ;;\n'
        '    mealie) echo "/mealie id-mealie running" ;;\n'
        '    resto-postgres) echo "/resto-postgres id-pg running" ;;\n'
        "    *) exit 1 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "inspect" ]; then\n'
        '  case "$2" in\n'
        "    resto-postiz|resto-temporal) exit 0 ;;\n"
        "  esac\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["MARKETING_PHASE2_ROLLBACK_APPROVED"] = "1"
    env["MARKETING_PHASE2_ROLLBACK_DELETE_DATA"] = "0"
    env.pop("APPDATA", None)
    result = subprocess.run(
        ["bash", str(root / "scripts/rollback-postiz-phase2.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = log.read_text(encoding="utf-8")
    assert "rm -f resto-postiz\n" in text
    assert "rm -f resto-temporal\n" in text
    assert "rm -f resto-mautic" not in text
    assert "rm -f resto-mautic-mysql" not in text
    assert "rm -f resto-postgres" not in text
    assert "rm -f mealie" not in text
    assert "Mautic was not removed." in result.stdout


def test_campaign_edit_and_activation_do_not_send(owner, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("Mautic should not be called for a local draft edit")

    monkeypatch.setattr("app.mautic.request", explode)
    created = owner.post("/api/campaigns", json={"name": "Paella", "subject": "Tonight", "body": "Two seatings"})
    assert created.status_code == 200
    edited = owner.patch(f"/api/campaigns/{created.json()['id']}", json={"name": "Paella night", "body": "Two seatings"})
    assert edited.status_code == 200
    assert edited.json()["status"] == "local"
    assert edited.json()["mautic_id"] == ""
    blocked = owner.post(f"/api/campaigns/{created.json()['id']}/activate")
    assert blocked.status_code == 409
    audience = owner.get("/api/audience")
    assert audience.status_code == 200
    assert audience.json()["contacts"] is None
    assert audience.json()["segments"] is None


def test_assistant_draft_is_not_published_without_a_model(owner):
    draft = owner.post("/api/assistant/draft", json={"purpose": "social", "brief": "Paella on Friday"})
    assert draft.status_code == 200
    body = draft.json()
    assert body["published"] is False
    assert body["source"] == "unconfigured"
    assert body["text"] == ""
    saved = owner.post("/api/assistant/save", json={"purpose": "social", "text": "Friday paella"})
    assert saved.status_code == 200
    assert saved.json()["published"] is False
    assert saved.json()["record"]["status"] == "draft"


def test_phase3_stops_before_docker_and_rollback_removes_only_the_dashboard(tmp_path):
    import os
    import stat
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/deploy-dashboard-phase3.sh"
    text = script.read_text(encoding="utf-8")
    assert text.index("backup-marketing-env.sh") < text.index("docker compose")
    assert "--no-deps --no-recreate command" in text
    assert "docker network create" not in text
    assert "sysctl -w" not in text
    assert "compose.public-edge.yml" not in text
    plain = subprocess.run(["bash", str(script)], cwd=root, capture_output=True, text=True)
    assert plain.returncode == 3, plain.stdout + plain.stderr
    assert "Nothing was started." in plain.stdout

    log = tmp_path / "docker.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "inspect" ] && [ "$2" = "resto-command" ]; then\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "inspect" ]; then\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["MARKETING_PHASE3_ROLLBACK_APPROVED"] = "1"
    env["MARKETING_PHASE3_ROLLBACK_DELETE_DATA"] = "0"
    env.pop("APPDATA", None)
    rolled = subprocess.run(["bash", str(root / "scripts/rollback-dashboard-phase3.sh")], cwd=root, env=env, capture_output=True, text=True)
    assert rolled.returncode == 0, rolled.stdout + rolled.stderr
    calls = log.read_text(encoding="utf-8")
    assert "rm -f resto-command\n" in calls
    assert "rm -f resto-mautic" not in calls
    assert "rm -f resto-postiz" not in calls
    assert "Mautic and Postiz were not removed." in rolled.stdout


def _map_count_env(tmp_path, go_text, runtime="65530"):
    import os
    import stat
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    go = tmp_path / "go"
    go.write_text(go_text, encoding="utf-8")
    proc = tmp_path / "proc"
    proc.write_text(runtime + "\n", encoding="utf-8")
    backup = tmp_path / "go.pre-marketing-mapcount"
    log = tmp_path / "sysctl.log"
    snap = tmp_path / "go-at-sysctl"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "sysctl"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'case "$1" in\n'
        "  -w)\n"
        '    val="${2#vm.max_map_count=}"\n'
        f'    printf "%s\\n" "$val" > "{proc}"\n'
        f'    cp "{go}" "{snap}"\n'
        "    ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["MARKETING_GO_FILE"] = str(go)
    env["MARKETING_MAP_COUNT_PROC"] = str(proc)
    env["MARKETING_MAP_COUNT_BACKUP"] = str(backup)
    env.pop("MARKETING_MAP_COUNT_APPROVED", None)
    env.pop("MARKETING_MAP_COUNT_ROLLBACK_APPROVED", None)
    return root, go, proc, backup, log, snap, env


def test_map_count_verifies_boot_file_before_runtime_and_rollback(tmp_path):
    import subprocess
    from pathlib import Path

    original = "#!/bin/bash\n# utility\n/usr/local/sbin/emhttp &\nexit 0\nsysctl -w vm.max_map_count=65530\n"
    root, go, proc, backup, log, snap, env = _map_count_env(tmp_path, original)
    real_before = Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8")
    refused = subprocess.run(["bash", str(root / "scripts/map-count-unraid.sh")], cwd=root, env=env, capture_output=True, text=True)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "Early exit or return on line 4." in refused.stdout
    assert "Nothing was changed." in refused.stdout
    assert go.read_text(encoding="utf-8") == original
    assert not backup.exists()
    assert not log.exists()

    approved = env.copy()
    approved["MARKETING_MAP_COUNT_APPROVED"] = "1"
    applied = subprocess.run(["bash", str(root / "scripts/map-count-unraid.sh")], cwd=root, env=approved, capture_output=True, text=True)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    rewritten = go.read_text(encoding="utf-8")
    assert backup.read_text(encoding="utf-8") == original
    assert snap.read_text(encoding="utf-8") == rewritten
    assert rewritten.index("vm.max_map_count=262144") < rewritten.index("exit 0")
    assert rewritten.count("vm.max_map_count") == 1
    assert "65530" not in rewritten
    assert proc.read_text(encoding="utf-8").strip() == "262144"
    assert Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8") == real_before

    again = subprocess.run(["bash", str(root / "scripts/map-count-unraid.sh")], cwd=root, env=approved, capture_output=True, text=True)
    assert again.returncode == 0, again.stdout + again.stderr
    assert go.read_text(encoding="utf-8") == rewritten
    assert backup.read_text(encoding="utf-8") == original
    assert "No duplicate" in again.stdout

    plain = env.copy()
    plain["MARKETING_MAP_COUNT_ROLLBACK_APPROVED"] = "0"
    held = subprocess.run(["bash", str(root / "scripts/map-count-rollback.sh")], cwd=root, env=plain, capture_output=True, text=True)
    assert held.returncode == 3, held.stdout + held.stderr
    assert go.read_text(encoding="utf-8") == rewritten
    assert "Nothing was changed." in held.stdout

    restore = env.copy()
    restore["MARKETING_MAP_COUNT_ROLLBACK_APPROVED"] = "1"
    rolled = subprocess.run(["bash", str(root / "scripts/map-count-rollback.sh")], cwd=root, env=restore, capture_output=True, text=True)
    assert rolled.returncode == 0, rolled.stdout + rolled.stderr
    assert go.read_text(encoding="utf-8") == original
    assert proc.read_text(encoding="utf-8").strip() == "65530"
    assert Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8") == real_before


def test_map_count_refuses_a_conflicting_complex_setting(tmp_path):
    import subprocess
    from pathlib import Path

    original = "#!/bin/bash\nif true; then sysctl -w vm.max_map_count=65530; fi\n"
    root, go, proc, backup, log, _snap, env = _map_count_env(tmp_path, original)
    env["MARKETING_MAP_COUNT_APPROVED"] = "1"
    result = subprocess.run(["bash", str(root / "scripts/map-count-unraid.sh")], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "will not rewrite" in result.stdout
    assert go.read_text(encoding="utf-8") == original
    assert not backup.exists()
    assert not log.exists()
    assert proc.read_text(encoding="utf-8").strip() == "65530"
    assert Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8").strip()


def test_phase2_backs_up_original_env_before_editing_it(tmp_path):
    import os
    import shutil
    import stat
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    passphrase = "phase2-original-env-passphrase"
    secret = "mautic-db-pass-test-value-9f3c"
    wt = tmp_path / "checkout"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], cwd=root, check=True)
    try:
        for name in ("deploy-postiz-phase2.sh", "fix-mautic-trusted-proxies.py"):
            shutil.copy(root / "scripts" / name, wt / "scripts" / name)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "docker"
        fake.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "exec" ]; then\n'
            "  printf '%s\\n' 'CREATE DATABASE `mautic`;' '-- Dump completed'\n"
            "  exit 0\n"
            "fi\n"
            'if [ "$1" = "inspect" ] && [ "$2" = "-f" ]; then\n'
            '  case "$3" in\n'
            "    *Running*) echo true ;;\n"
            "    *Health*) echo healthy ;;\n"
            '    *) echo "/$4 id-$4" ;;\n'
            "  esac\n"
            "  exit 0\n"
            "fi\n"
            'if [ "$1" = "inspect" ]; then\n'
            '  case "$2" in\n'
            "    resto-mautic|resto-mautic-mysql|resto-mautic-cron|resto-mautic-worker) exit 0 ;;\n"
            "  esac\n"
            "  exit 1\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        original = "\n".join(
            [
                "APPDATA=/mnt/cache/appdata/surveycafe-marketing",
                "BIND_ADDR=100.116.48.120",
                f"MAUTIC_DB_PASSWORD={secret}",
                "MAUTIC_DB_ROOT_PASSWORD=mautic-root-pass-test-value-9f3c",
                "POSTIZ_DB_PASSWORD=postiz-db-pass-test-value-9f3c",
                "POSTIZ_JWT_SECRET=postiz-jwt-secret-test-value-9f3c",
                "TEMPORAL_DB_PASSWORD=temporal-db-pass-test-value-9f3c",
                "COMMAND_SECRET_KEY=command-secret-key-test-value-9f3c",
                "COMMAND_ADMIN_PASSWORD=command-admin-pass-test-value",
                "COMMAND_DB_PASSWORD=command-db-pass-test-value-9f3c",
                "COMMAND_ADMIN_EMAIL=surveycafedowntown@gmail.com",
                "MAUTIC_TRUSTED_PROXIES=172.16.0.0/12",
                "",
            ]
        )
        env_file = wt / ".env"
        env_file.write_text(original, encoding="utf-8")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, check=True, capture_output=True, text=True).stdout.strip()
        env = os.environ.copy()
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
        env["MARKETING_PHASE2_APPROVED"] = "1"
        env["MARKETING_DEPLOY_COMMIT"] = head
        env["MARKETING_ENV_PASSPHRASE"] = passphrase
        env["MARKETING_BACKUP_DIR"] = str(tmp_path / "db-backups")
        env["MARKETING_ENV_BACKUP_DIR"] = str(tmp_path / "env-backups")
        env.pop("MARKETING_MAP_COUNT_APPROVED", None)
        result = subprocess.run(
            ["bash", str(wt / "scripts/deploy-postiz-phase2.sh")],
            cwd=wt,
            env=env,
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "The original marketing .env was backed up before any configuration change." in result.stdout
        assert result.stdout.index("backed up before any configuration change") < result.stdout.index(
            "Corrected MAUTIC_TRUSTED_PROXIES"
        )
        assert passphrase not in combined
        assert secret not in combined
        enc = next((tmp_path / "env-backups").glob("phase2-*-before/marketing.env.enc"))
        plain = tmp_path / "restored.env"
        decrypted = subprocess.run(
            [
                "bash",
                "-c",
                'source scripts/marketing-env-crypto.sh; marketing_env_decrypt "$1" "$2"',
                "bash",
                str(enc),
                str(plain),
            ],
            cwd=wt,
            env={**env, "MARKETING_ENV_PASSPHRASE": passphrase},
            capture_output=True,
            text=True,
        )
        assert decrypted.returncode == 0, decrypted.stdout + decrypted.stderr
        assert plain.read_text(encoding="utf-8") == original
        live = env_file.read_text(encoding="utf-8")
        assert "MAUTIC_TRUSTED_PROXIES='[]'" in live
        assert f"MAUTIC_DB_PASSWORD={secret}" in live
        assert "172.16.0.0/12" not in live

        valid = original.replace("MAUTIC_TRUSTED_PROXIES=172.16.0.0/12", "MAUTIC_TRUSTED_PROXIES='[]'")
        env_file.write_text(valid, encoding="utf-8")
        env["MARKETING_ENV_BACKUP_DIR"] = str(tmp_path / "env-backups-valid")
        kept = subprocess.run(
            ["bash", str(wt / "scripts/deploy-postiz-phase2.sh")],
            cwd=wt,
            env=env,
            capture_output=True,
            text=True,
        )
        assert kept.returncode == 2, kept.stdout + kept.stderr
        assert "Mautic configuration was not modified." in kept.stdout
        assert "Corrected MAUTIC_TRUSTED_PROXIES" not in kept.stdout
        assert env_file.read_text(encoding="utf-8") == valid
        assert passphrase not in kept.stdout + kept.stderr
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=root, check=False)
