#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kapowarr_unmatched as ku


class FolderMetaTests(unittest.TestCase):
    def test_year_in_folder_name(self) -> None:
        title, year, tree = ku.folder_meta("/comics/DC Comics/Future State Harley Quinn (2021)")
        self.assertEqual(title, "Future State Harley Quinn")
        self.assertEqual(year, 2021)
        self.assertEqual(tree, "DC Comics")

    def test_new_52_infers_2011(self) -> None:
        title, year, tree = ku.folder_meta("/comics/DC New 52/Green Arrow")
        self.assertEqual(title, "Green Arrow")
        self.assertEqual(year, 2011)
        self.assertEqual(tree, "DC New 52")

    def test_rebirth_infers_2016(self) -> None:
        title, year, _tree = ku.folder_meta("/comics/dc rebirth/Suicide Squad")
        self.assertEqual(title, "Suicide Squad")
        self.assertEqual(year, 2016)


class SearchQueryTests(unittest.TestCase):
    def test_future_state_family(self) -> None:
        self.assertEqual(ku.search_query("Future State Harley Quinn"), "future state")
        self.assertEqual(ku.search_query("Future State: The Flash"), "future state")

    def test_two_word_default(self) -> None:
        self.assertEqual(ku.search_query("Green Arrow Rebirth"), "green arrow")


class SkipTests(unittest.TestCase):
    def test_skips_manga_and_previews(self) -> None:
        self.assertEqual(ku.should_skip_folder("/manga/Bleach"), "manga")
        self.assertEqual(
            ku.should_skip_folder(
                "/comics/Marvel/All-New Marvel NOW! Previews (2013)"
            ),
            "skip-list",
        )
        self.assertEqual(
            ku.should_skip_folder("/comics/Pika Édition/MPD-Psycho (2004)"),
            "skip-list",
        )
        self.assertEqual(
            ku.should_skip_folder("/comics/dc rebirth/DC Rebirth Omnibus (2016)"),
            "skip-list",
        )

    def test_skips_foreign_unless_requested(self) -> None:
        path = "/comics/ECC Ediciones/Aquaman (2012)"
        self.assertEqual(ku.should_skip_folder(path), "foreign")
        self.assertIsNone(ku.should_skip_folder(path, include_foreign=True))


class PickVolumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.future_state = [
            {"id": 133037, "name": "Future State: Harley Quinn", "start_year": 2021, "count_of_issues": 2, "publisher": {"name": "DC Comics"}},
            {"id": 133036, "name": "Future State: The Flash", "start_year": 2021, "count_of_issues": 2, "publisher": {"name": "DC Comics"}},
            {"id": 999, "name": "Future State: Harley Quinn", "start_year": 2021, "count_of_issues": 2, "publisher": {"name": "Marvel"}},
        ]
        self.green_arrow = [
            {"id": 4003, "name": "Green Arrow", "start_year": 1988, "count_of_issues": 139, "publisher": {"name": "DC Comics"}},
            {"id": 43716, "name": "Green Arrow", "start_year": 2011, "count_of_issues": 52, "publisher": {"name": "DC Comics"}},
            {"id": 91813, "name": "Green Arrow", "start_year": 2016, "count_of_issues": 50, "publisher": {"name": "DC Comics"}},
            {"id": 91081, "name": "Green Arrow: Rebirth", "start_year": 2016, "count_of_issues": 1, "publisher": {"name": "DC Comics"}},
        ]

    def test_colon_and_publisher(self) -> None:
        picked = ku.pick_comicvine_volume(
            self.future_state, "Future State Harley Quinn", 2021, "DC Comics"
        )
        self.assertEqual(picked["id"], 133037)

    def test_year_picks_rebirth_not_new_52(self) -> None:
        picked = ku.pick_comicvine_volume(self.green_arrow, "Green Arrow", 2016, "DC Comics")
        self.assertEqual(picked["id"], 91813)

    def test_new_52_window_picks_2011(self) -> None:
        picked = ku.pick_comicvine_volume(self.green_arrow, "Green Arrow", None, "DC New 52")
        self.assertEqual(picked["id"], 43716)

    def test_rebirth_one_shot_keeps_rebirth_in_title(self) -> None:
        picked = ku.pick_comicvine_volume(
            self.green_arrow, "Green Arrow Rebirth", 2016, "DC Comics"
        )
        self.assertEqual(picked["id"], 91081)

    def test_no_guess_when_title_missing(self) -> None:
        self.assertIsNone(
            ku.pick_comicvine_volume(self.green_arrow, "Black Arrow", 2016, "DC Comics")
        )


class ImportRowTests(unittest.TestCase):
    def test_keeps_archives_only(self) -> None:
        rows = ku.import_rows_for_folder(
            [
                "/comics/DC Comics/Future State Harley Quinn (2021)/Future State - Harley Quinn 1.cbr",
                "/comics/DC Comics/Future State Harley Quinn (2021)/cover.jpg",
                "/manga/Bleach/Bleach 001.cbz",
            ],
            133037,
        )
        self.assertEqual(
            rows,
            [
                {
                    "filepath": "/comics/DC Comics/Future State Harley Quinn (2021)/Future State - Harley Quinn 1.cbr",
                    "id": 133037,
                }
            ],
        )

    def test_relative_folder(self) -> None:
        self.assertEqual(
            ku.relative_volume_folder("/comics/DC Comics/Green Arrow (2016)"),
            "DC Comics/Green Arrow (2016)",
        )


class ExistingVolumeTests(unittest.TestCase):
    def test_matches_title_and_year(self) -> None:
        volumes = [
            {
                "id": 87,
                "comicvine_id": 43019,
                "title": "All Star Western",
                "year": 2011,
                "folder": "/comics/DC Comics/All Star Western (2011)",
                "issues_downloaded": 1,
            }
        ]
        found = ku.existing_volume_for_folder(volumes, "/comics/DC New 52/All-Star Western")
        self.assertEqual(found["comicvine_id"], 43019)

    def test_uses_imprint_root_volume(self) -> None:
        volumes = [
            {
                "id": 55,
                "comicvine_id": 94661,
                "title": "Shade, The Changing Girl",
                "year": 2016,
                "folder": "/comics/dc rebirth",
                "issues_downloaded": 3,
            }
        ]
        found = ku.existing_volume_for_folder(
            volumes, "/comics/dc rebirth/Shade, the Changing Girl"
        )
        self.assertEqual(found["comicvine_id"], 94661)


if __name__ == "__main__":
    unittest.main()
