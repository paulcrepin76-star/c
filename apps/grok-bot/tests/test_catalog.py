from pathlib import Path

import yaml

from app import catalog
from app.settings import settings


def test_catalog_apps_have_what_compose_needs():
    for app in catalog.CATALOG:
        assert app["slug"] and app["image"] and app["summary"]
        service = catalog.service_definition(app)
        assert service["restart"] == "unless-stopped"
        assert service["networks"] == ["resto"]
        assert service["container_name"] == f"resto-{app['slug']}"


def test_install_writes_a_mergeable_compose_file():
    catalog.add_service(catalog.find_app("ntfy"))
    path = Path(settings.repo_dir) / "compose.extra.yml"
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["services"]["ntfy"]["image"].startswith("binwiederhier/ntfy")
    assert data["services"]["ntfy"]["ports"] == ["8055:80"]
    assert catalog.installed() == ["ntfy"]
    assert catalog.remove_service("ntfy") is True
    assert catalog.installed() == []


def test_second_install_keeps_the_first():
    catalog.add_service(catalog.find_app("ntfy"))
    catalog.add_service(catalog.find_app("dozzle"))
    assert catalog.installed() == ["dozzle", "ntfy"]


def test_custom_image_gets_a_slug_and_a_volume():
    app = catalog.custom_app("", "louislam/uptime-kuma:1", 3011)
    assert app["slug"] == "uptime-kuma"
    service = catalog.service_definition(app)
    assert service["ports"] == ["3011:3011"]


def test_a_port_already_in_compose_is_refused():
    assert catalog.port_conflict({"port": 8088}) != ""
    assert catalog.port_conflict({"port": 8055}) == ""


def test_catalog_rows_flag_what_is_installed():
    catalog.add_service(catalog.find_app("adminer"))
    rows = {row["slug"]: row for row in catalog.catalog_rows()}
    assert rows["adminer"]["installed"] is True
    assert rows["ntfy"]["installed"] is False
