#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "kavita-libraries.json"


class KavitaLibrariesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads(CATALOG.read_text())
        self.libraries = {row["name"]: row for row in self.catalog["libraries"]}

    def test_points_at_the_folders_paul_reads(self) -> None:
        expected = {
            "Absolute DC": "/books/comics/Absolute DC",
            "DC New 52": "/books/comics/DC New 52",
            "DC Rebirth": "/books/comics/dc rebirth",
            "Marvel": "/books/comics/Marvel",
            "Spider-Man": "/books/comics/Amazing spiderman",
            "DC Comics": "/books/comics/DC Comics",
        }
        self.assertEqual({name: row["folder"] for name, row in self.libraries.items()}, expected)

    def test_uses_flexible_comic_type_not_comicvine(self) -> None:
        for row in self.libraries.values():
            self.assertEqual(row["type"], 1)

    def test_does_not_mount_the_whole_comics_root(self) -> None:
        folders = {row["folder"] for row in self.libraries.values()}
        self.assertNotIn("/books/comics", folders)
        self.assertNotIn("/books", folders)
        self.assertTrue(all(folder.startswith("/books/comics/") for folder in folders))

    def test_excludes_comicarr_scan_index(self) -> None:
        self.assertIn(".comicarr-scan", self.catalog["exclude_patterns"])

    def test_uses_a_valid_kavita_metadata_provider(self) -> None:
        # Kavita only accepts Hardcover=2, Mangabaka=3, ComicBookRoundup=4.
        self.assertIn(self.catalog["metadata_provider"], (2, 3, 4))


if __name__ == "__main__":
    unittest.main()
