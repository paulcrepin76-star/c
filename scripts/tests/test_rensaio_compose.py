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


if __name__ == "__main__":
    unittest.main()
