from app import commands


def test_plain_words_map_to_tools():
    assert commands.parse("status")["tool"] == "restaurant_status"
    assert commands.parse("How are things")["tool"] == "restaurant_status"
    assert commands.parse("ça va?")["tool"] == "restaurant_status"
    assert commands.parse("server")["tool"] == "server_status"
    assert commands.parse("apps")["tool"] == "list_catalog"
    assert commands.parse("sync")["tool"] == "run_sync"


def test_commands_carry_the_app_name():
    assert commands.parse("logs n8n") == {"tool": "app_logs", "args": {"app": "n8n"}}
    assert commands.parse("restart resto-core") == {"tool": "restart_app", "args": {"app": "resto-core"}}
    assert commands.parse("stop metabase")["tool"] == "stop_app"
    assert commands.parse("start metabase")["tool"] == "start_app"


def test_install_splits_catalog_slugs_from_raw_images():
    assert commands.parse("install ntfy") == {"tool": "install_app", "args": {"app": "ntfy"}}
    assert commands.parse("install uptime-kuma on port 3011") == {
        "tool": "install_app",
        "args": {"app": "uptime-kuma", "port": 3011},
    }
    assert commands.parse("install louislam/uptime-kuma:1 3011") == {
        "tool": "install_app",
        "args": {"app": "", "image": "louislam/uptime-kuma:1", "port": 3011},
    }


def test_update_alone_is_the_whole_stack():
    assert commands.parse("update") == {"tool": "update_stack", "args": {}}
    assert commands.parse("update everything") == {"tool": "update_stack", "args": {}}
    assert commands.parse("update n8n") == {"tool": "update_app", "args": {"app": "n8n"}}


def test_nonsense_returns_nothing():
    assert commands.parse("tell me a joke about wine") is None


def test_short_commands_are_shortcuts_and_sentences_are_not():
    assert commands.shortcut("restart n8n") == {"tool": "restart_app", "args": {"app": "n8n"}}
    assert commands.shortcut("status")["tool"] == "restaurant_status"
    assert commands.shortcut("install ntfy")["tool"] == "install_app"
    assert commands.shortcut("How are things at the cafe today?") is None
    assert commands.shortcut("n8n looks stuck, bounce it for me") is None
    assert commands.shortcut("") is None
