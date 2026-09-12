#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PARSER = Path(__file__).resolve().parents[2] / "docker" / "comics" / "patches" / "manga_parser.py"


def load_parser():
    spec = importlib.util.spec_from_file_location("manga_parser_patch", PARSER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MangaParserTitleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parser = load_parser()

    def test_vol_ch_with_title(self) -> None:
        match = self.parser._PAT_VOL_CH_ABBR.match("MPD Psycho - Vol.3 Ch.13 - Umamiya Akio 1")
        self.assertIsNotNone(match)
        self.assertEqual(match.group("chapter"), "13")
        self.assertEqual(match.group("volume"), "3")

    def test_vol_ch_decimal(self) -> None:
        match = self.parser._PAT_VOL_CH_ABBR.match(
            "MPD Psycho - Vol.11 Ch.69.2 - Dead Man's Galaxy Days 2"
        )
        self.assertEqual(match.group("chapter"), "69.2")

    def test_chapter_underscore_title(self) -> None:
        parsed = self.parser.parse_manga_filename(
            "Chapter 100_ Apocalypse Now.cbz",
            series_name="MPD Psycho",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["chapter_number"], 100.0)

    def test_still_parses_plain_chapter(self) -> None:
        parsed = self.parser.parse_manga_filename("chapter 12.cbz", series_name="MPD Psycho")
        self.assertEqual(parsed["chapter_number"], 12.0)


if __name__ == "__main__":
    unittest.main()
