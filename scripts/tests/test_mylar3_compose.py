#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker" / "comics" / "compose.mylar3.yml"
INSTALL = ROOT / "scripts" / "mylar3-install.sh"


class Mylar3ComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = COMPOSE.read_text(encoding="utf-8")

    def test_compose_is_marked_historical(self) -> None:
        self.assertIn("Historical. Mylar3 was removed.", self.text)

    def test_uses_linuxserver_image_and_default_ui_port(self) -> None:
        self.assertIn("lscr.io/linuxserver/mylar3:latest", self.text)
        self.assertIn("8090:8090", self.text)
        self.assertIn("container_name: mylar3", self.text)

    def test_comics_and_own_downloads_are_mounted(self) -> None:
        self.assertIn("/mnt/user/media/book/comics}:/comics", self.text)
        self.assertIn("/mnt/user/downloads/mylar3}:/downloads", self.text)
        self.assertIn("/mnt/user/appdata/mylar3}:/config", self.text)
        self.assertIn("/mnt/user/downloads}:/data/downloads", self.text)
        self.assertIn("/mnt/remotes/whatbox/Downloads}:/home/deicide/Downloads", self.text)

    def test_joins_media_net_and_skips_manga(self) -> None:
        self.assertIn("media-net", self.text)
        self.assertNotIn("/manga", self.text)
        self.assertNotIn("/series", self.text)
        self.assertNotIn("ghcr.io/frankieramirez/comicarr", self.text)
        self.assertNotIn("/mnt/user/appdata/comicarr", self.text)


class Mylar3InstallScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = INSTALL.read_text(encoding="utf-8")

    def test_does_not_start_comicarr_or_stop_kapowarr(self) -> None:
        self.assertIn("Does not start Comicarr", self.text)
        self.assertIn("this script will not start it", self.text)
        self.assertNotIn("docker start comicarr", self.text)
        self.assertNotIn("docker stop kapowarr", self.text)
        self.assertNotIn("docker stop rensaio", self.text)

    def test_refuses_to_reinstall_unless_asked(self) -> None:
        self.assertIn("Mylar3 was removed. Do not reinstall unless asked.", self.text)
        self.assertIn('MYLAR3_REINSTALL:-', self.text)

    def test_skips_library_import_and_copies_compose(self) -> None:
        self.assertIn("compose.mylar3.yml", self.text)
        self.assertIn("mylar3_config.py", self.text)
        self.assertIn("comicvine_api_key", self.text)
        self.assertIn("Do not use Manage / Import / Rename", self.text)
        self.assertIn("200|301|302|303|307|308", self.text)
        self.assertIn(".zzz_check", self.text)
        self.assertNotIn("libraryScan", self.text)
        self.assertNotIn("addComic", self.text)


if __name__ == "__main__":
    unittest.main()
