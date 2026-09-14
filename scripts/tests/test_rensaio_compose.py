#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "docker" / "comics" / "compose.rensaio.yml"


class RensaioComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = COMPOSE.read_text(encoding="utf-8")

    def test_uses_official_image_and_ui_port(self) -> None:
        self.assertIn("maxpiva/rensaio:latest", self.text)
        self.assertIn("9833:9833", self.text)

    def test_manga_library_is_the_series_root(self) -> None:
        self.assertIn("/mnt/user/media/book/manga}:/series", self.text)

    def test_does_not_mount_comics_or_comicarr(self) -> None:
        self.assertNotIn("comicarr", self.text)
        self.assertNotIn("/comics", self.text)


class RensaioInstallScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (Path(__file__).resolve().parents[1] / "rensaio-install.sh").read_text(
            encoding="utf-8"
        )

    def test_installs_search_sources_and_skips_wizard_import(self) -> None:
        self.assertIn("eu.kanade.tachiyomi.extension.all.mangadex", self.text)
        self.assertIn("eu.kanade.tachiyomi.extension.all.mangafire", self.text)
        self.assertIn("eu.kanade.tachiyomi.extension.en.vizshonenjump", self.text)
        self.assertIn("eu.kanade.tachiyomi.extension.en.kodansha", self.text)
        self.assertIn("isWizardSetupComplete = true", self.text)
        self.assertIn("nsfwVisibility = \"Show\"", self.text)
        self.assertIn("flareSolverrUrl = \"http://flaresolverr:8191\"", self.text)
        self.assertNotIn("eu.kanade.tachiyomi.extension.all.mangaup", self.text)
        self.assertNotIn("docker start comicarr", self.text)


class RensaioQueueScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (Path(__file__).resolve().parents[1] / "rensaio-queue.sh").read_text(
            encoding="utf-8"
        )

    def test_clears_waiting_downloads_only(self) -> None:
        self.assertIn("action=Delete", self.text)
        self.assertIn("status=Waiting", self.text)
        self.assertIn("Does not rename series", self.text)
        self.assertNotIn("docker start comicarr", self.text)
        self.assertNotIn("/api/serie/rename", self.text)


if __name__ == "__main__":
    unittest.main()
