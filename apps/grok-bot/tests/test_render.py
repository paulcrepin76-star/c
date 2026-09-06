from app import render


def _status(**fridges):
    return {
        "sales": {"today": 204.0, "month_to_date": 1224.0, "tickets_today": 1, "avg_ticket_today": 204.0},
        "month": {"food_cost_pct": 45.4, "wine_cost_pct": 0.0, "operating_profit": 668.88},
        "fridges": {"alerts": 0, "online": 7, "total": 7, "out_of_range": [], **fridges},
        "needs_you": [],
    }


def test_silent_sensors_are_not_reported_as_in_range():
    reply = render.restaurant(_status(online=0))
    assert "none of the 7 are reporting" in reply


def test_partial_coverage_says_how_many_answered():
    assert "3 of 7 reporting" in render.restaurant(_status(online=3))


def test_full_coverage_is_the_short_sentence():
    assert "all 7 in range" in render.restaurant(_status())


def test_an_alert_names_the_fridge():
    reply = render.restaurant(_status(alerts=1, out_of_range=[{"name": "Prep fridge", "temp_f": 46.2}]))
    assert "1 out of range — Prep fridge 46.2F" in reply


def test_a_dead_cellar_app_says_so():
    assert "Could not read" in render.restaurant({"error": "timed out"})


def test_server_lines_mark_what_is_down():
    reply = render.server(
        {
            "engine": {"running": 1},
            "host": {"load": [0.4], "memory_used_pct": 17.6, "disk": {"used_pct": 8.9, "free_gb": 230.7}},
            "containers": [
                {"name": "resto-core", "state": "running", "health": "healthy", "ports": ["8088->8080"]},
                {"name": "resto-n8n", "state": "exited", "health": "", "ports": []},
            ],
            "not_running": ["resto-n8n"],
            "unhealthy": [],
        }
    )
    assert "1 of 2 containers running" in reply
    assert "resto-core :8088 — up" in reply
    assert "resto-n8n — down" in reply


def test_install_points_at_the_new_address():
    reply = render.installed({"ok": True, "app": "ntfy", "image": "binwiederhier/ntfy:latest", "port": 8055})
    assert "Installed ntfy" in reply
    assert ":8055" in reply
