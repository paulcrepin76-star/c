#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comicarr_enable_manga_search as manga


class MangaSearchHelperTests(unittest.TestCase):
    def test_priority_alias_drops_foreign_titles(self) -> None:
        existing = "ワンピース##One Piece. Большой куш##One Piece"
        self.assertEqual(manga.priority_alternate_search(existing, "One Piece"), "!!One Piece")

    def test_priority_alias_replaces_previous_bang_prefix(self) -> None:
        existing = "!!古い名前##Bleach"
        self.assertEqual(manga.priority_alternate_search(existing, "Bleach"), "!!Bleach")

    def test_shangri_short_name_is_not_the_japanese_title(self) -> None:
        existing = "シャングリラ・フロンティア～クソゲーハンター、神ゲーに挑まんとす～"
        self.assertEqual(
            manga.priority_alternate_search(existing, "Shangri-La Frontier"),
            "!!Shangri-La Frontier",
        )

    def test_chapter_date_prefers_publish_at(self) -> None:
        self.assertEqual(
            manga.chapter_date(
                {
                    "publishAt": "2001-08-07T00:00:00+00:00",
                    "readableAt": "2024-01-01T00:00:00+00:00",
                }
            ),
            "2001-08-07",
        )

    def test_fallback_year_and_bad_year(self) -> None:
        self.assertEqual(manga.fallback_series_date("1999"), "1999-01-01")
        self.assertEqual(manga.fallback_series_date("9999"), "2000-01-01")
        self.assertEqual(manga.fallback_series_date(None), "2000-01-01")

    def test_parse_chapter_number(self) -> None:
        self.assertEqual(manga.parse_chapter_number("69.2"), 69.2)
        self.assertEqual(manga.parse_chapter_number("001"), 1.0)
        self.assertIsNone(manga.parse_chapter_number(""))

    def test_session_token_is_cached(self) -> None:
        manga._SESSION_TOKEN = "cached-cookie"
        self.assertEqual(manga.session_token(), "cached-cookie")
        manga._SESSION_TOKEN = None

    def test_erotica_rating_is_added_once(self) -> None:
        self.assertEqual(
            manga.with_erotica_rating("safe,suggestive"),
            "safe,suggestive,erotica",
        )
        self.assertEqual(
            manga.with_erotica_rating("safe,suggestive,erotica"),
            "safe,suggestive,erotica",
        )

    def test_merge_feed_keeps_earliest_date_and_first_volume(self) -> None:
        store: dict[float, dict] = {}
        manga.merge_feed_chapter(store, {"chapter": "1", "publishAt": "1999-09-21", "volume": "1"})
        manga.merge_feed_chapter(store, {"chapter": "1", "publishAt": "1999-10-01", "volume": "2"})
        self.assertEqual(store[1.0]["date"], "1999-09-21")
        self.assertEqual(store[1.0]["volume"], "1")


if __name__ == "__main__":
    unittest.main()
