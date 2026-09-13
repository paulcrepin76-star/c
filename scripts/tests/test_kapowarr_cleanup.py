#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kapowarr_cleanup as kc


class ParseTests(unittest.TestCase):
    def test_issue_from_padded_name(self) -> None:
        self.assertEqual(kc.parse_issue_number("Action Comics 0957.cbr"), 957.0)

    def test_issue_from_kapowarr_name(self) -> None:
        self.assertEqual(
            kc.parse_issue_number("Action Comics (2016) Volume 03 Issue 957.cbr"),
            957.0,
        )

    def test_series_from_padded_name(self) -> None:
        self.assertEqual(kc.infer_series_title("Action Comics 0957.cbr"), "Action Comics")

    def test_empty_archive_only_tiny_comics(self) -> None:
        self.assertTrue(
            kc.is_empty_archive({"filepath": "/comics/DC Comics/Foo/Foo 001.cbr", "size": 0})
        )
        self.assertFalse(
            kc.is_empty_archive({"filepath": "/comics/DC Comics/Foo/Foo 001.cbr", "size": 12_000_000})
        )
        self.assertFalse(
            kc.is_empty_archive({"filepath": "/manga/Bleach/Bleach 001.cbz", "size": 0})
        )


class DuplicateTests(unittest.TestCase):
    def test_deletes_only_empty_twin(self) -> None:
        volumes = [
            {
                "id": 201,
                "title": "Eternity Girl",
                "year": 2018,
                "folder": "/comics/DC Comics/Eternity Girl (2018)",
                "issues_downloaded": 6,
            },
            {
                "id": 225,
                "title": "Eternity Girl",
                "year": 2018,
                "folder": "/comics/DC Comics/Eternity Girl (2018)",
                "issues_downloaded": 0,
            },
        ]
        self.assertEqual(kc.empty_duplicate_volume_ids(volumes), [225])

    def test_keeps_different_years(self) -> None:
        volumes = [
            {
                "id": 82,
                "title": "Action Comics",
                "year": 1938,
                "folder": "/comics/DC Comics/Action Comics (1938)",
                "issues_downloaded": 0,
            },
            {
                "id": 228,
                "title": "Action Comics",
                "year": 2016,
                "folder": "/comics/DC Comics/Action Comics (2016)",
                "issues_downloaded": 6,
            },
        ]
        self.assertEqual(kc.empty_duplicate_volume_ids(volumes), [])


class ImportTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.volumes = [
            {
                "id": 82,
                "comicvine_id": 18005,
                "title": "Action Comics",
                "year": 1938,
                "folder": "/comics/DC Comics/Action Comics (1938)",
                "issues_downloaded": 0,
            },
            {
                "id": 228,
                "comicvine_id": 91078,
                "title": "Action Comics",
                "year": 2016,
                "folder": "/comics/DC Comics/Action Comics (2016)",
                "issues_downloaded": 6,
            },
            {
                "id": 109,
                "comicvine_id": 111,
                "title": "Batgirl",
                "year": 2025,
                "folder": "/comics/DC Comics/Batgirl (2025)",
                "issues_downloaded": 23,
            },
            {
                "id": 104,
                "comicvine_id": 222,
                "title": "Batgirl",
                "year": 2000,
                "folder": "/comics/DC Comics/Batgirl (2025)",
                "issues_downloaded": 52,
            },
        ]

    def test_rebirth_action_comics_moves_out_of_1938(self) -> None:
        cv_id, rename = kc.target_for_unmatched_file(
            "/comics/DC Comics/Action Comics (1938)/Action Comics 0963.cbr",
            self.volumes,
        )
        self.assertEqual(cv_id, 91078)
        self.assertTrue(rename)

    def test_single_owner_folder_stays_put(self) -> None:
        extra = list(self.volumes)
        extra.append(
            {
                "id": 83,
                "comicvine_id": 76720,
                "title": "Action Comics: Futures End",
                "year": 2014,
                "folder": "/comics/DC Comics/Action Comics Futures End (2014)",
                "issues_downloaded": 1,
            }
        )
        cv_id, rename = kc.target_for_unmatched_file(
            "/comics/DC Comics/Action Comics Futures End (2014)/Action Comics Futures End 001.cbr",
            extra,
        )
        self.assertEqual(cv_id, 76720)
        self.assertFalse(rename)

    def test_shared_folder_is_not_guessed(self) -> None:
        cv_id, rename = kc.target_for_unmatched_file(
            "/comics/DC Comics/Batgirl (2025)/Batgirl 001.cbr",
            self.volumes,
        )
        self.assertIsNone(cv_id)
        self.assertFalse(rename)

    def test_manga_is_ignored(self) -> None:
        cv_id, _rename = kc.target_for_unmatched_file(
            "/manga/Bleach/Bleach 001.cbz",
            self.volumes,
        )
        self.assertIsNone(cv_id)

    def test_group_import_splits_move_and_keep(self) -> None:
        rows = [
            {"filepath": "/comics/DC Comics/Action Comics (1938)/Action Comics 0963.cbr", "cv": None},
            {
                "filepath": "/comics/DC Comics/Action Comics Futures End (2014)/Action Comics Futures End 001.cbr",
                "cv": {"id": 76720},
            },
        ]
        volumes = self.volumes + [
            {
                "id": 83,
                "comicvine_id": 76720,
                "title": "Action Comics: Futures End",
                "year": 2014,
                "folder": "/comics/DC Comics/Action Comics Futures End (2014)",
                "issues_downloaded": 1,
            }
        ]
        keep, move, skipped = kc.group_import_rows(rows, volumes)
        self.assertEqual(move, [{"filepath": rows[0]["filepath"], "id": 91078}])
        self.assertEqual(keep, [{"filepath": rows[1]["filepath"], "id": 76720}])
        self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()
