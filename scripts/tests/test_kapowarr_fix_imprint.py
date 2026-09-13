#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kapowarr_fix_imprint as kf


class FolderTests(unittest.TestCase):
    def test_imprint_root(self) -> None:
        self.assertTrue(kf.is_imprint_root_folder("/comics/DC New 52"))
        self.assertTrue(kf.is_imprint_root_folder("/comics/dc rebirth/"))
        self.assertFalse(kf.is_imprint_root_folder("/comics/DC New 52/Action Comics"))

    def test_target_stays_under_imprint(self) -> None:
        self.assertEqual(
            kf.target_volume_folder("Batgirl: Endgame", 2015, "/comics/DC New 52"),
            "/comics/DC New 52/Batgirl - Endgame (2015)",
        )

    def test_wrong_era_gets_own_folder_not_rebirth_series(self) -> None:
        self.assertEqual(
            kf.target_volume_folder("Suicide Squad", 1987, "/comics/dc rebirth"),
            "/comics/dc rebirth/Suicide Squad (1987)",
        )

    def test_year_named_folder_keeps_imprint_parent(self) -> None:
        self.assertTrue(kf.folder_missing_year("/comics/DC New 52/Action Comics", 2011))
        self.assertFalse(kf.folder_missing_year("/comics/DC New 52/Action Comics (2011)", 2011))
        self.assertEqual(
            kf.year_named_folder("/comics/DC New 52/Action Comics", "Action Comics", 2011),
            "/comics/DC New 52/Action Comics (2011)",
        )

    def test_old_omnibus_leftover_is_empty_2016_hardcover(self) -> None:
        leftover = {
            "id": 37,
            "title": "DC Rebirth Omnibus",
            "year": 2016,
            "issues_downloaded": 0,
            "folder": "/comics/dc rebirth/DC Rebirth Omnibus (2016)",
        }
        self.assertTrue(kf.is_old_omnibus_leftover(leftover))
        self.assertTrue(kf.should_drop_old_omnibus(leftover, 0))
        self.assertFalse(kf.should_drop_old_omnibus(leftover, 1))
        leftover["issues_downloaded"] = 1
        self.assertFalse(kf.is_old_omnibus_leftover(leftover))

    def test_leading_issue_ignores_chapter_subtitle(self) -> None:
        self.assertEqual(
            kf.leading_issue_number("Action Comics 031- Infected Chapter 1.cbz", "Action Comics"),
            31.0,
        )
        self.assertEqual(
            kf.leading_issue_number("Action Comics 023.1 - Born in Flames.cbz", "Action Comics"),
            23.1,
        )


class LooseFileTests(unittest.TestCase):
    FILES = [
        "/comics/DC New 52/Batgirl - Endgame.cbz",
        "/comics/DC New 52/Harley Quinn Annual.cbz",
        "/comics/DC New 52/Harley Quinn Holiday Special.cbz",
        "/comics/DC New 52/Green Lantern - NewGods Godhead.cbz",
        "/comics/DC New 52/Action Comics 001.cbz",
    ]

    def test_endgame_and_godhead(self) -> None:
        self.assertEqual(
            kf.pick_loose_file("Batgirl: Endgame", self.FILES),
            "/comics/DC New 52/Batgirl - Endgame.cbz",
        )
        self.assertEqual(
            kf.pick_loose_file("Green Lantern/New Gods: Godhead", self.FILES),
            "/comics/DC New 52/Green Lantern - NewGods Godhead.cbz",
        )

    def test_does_not_steal_other_harley_or_action(self) -> None:
        self.assertEqual(
            kf.pick_loose_file("Harley Quinn Annual", self.FILES),
            "/comics/DC New 52/Harley Quinn Annual.cbz",
        )
        self.assertIsNone(kf.pick_loose_file("Action Comics", self.FILES))
        self.assertIsNone(
            kf.pick_loose_file(
                "Teen Titans",
                ["/comics/DC New 52/Teen Titans (2014) Futures End.cbz"],
            )
        )
        self.assertEqual(
            kf.loose_file_score(
                "Teen Titans",
                "Teen Titans (2014) Futures End.cbz",
            ),
            0,
        )
        self.assertGreaterEqual(
            kf.loose_file_score(
                "Trinity of Sin: The Phantom Stranger: Futures End",
                "Trinity of Sin Phantom Stranger Futures End.cbz",
            ),
            80,
        )
        self.assertIsNone(kf.pick_loose_file("Batgirl: Endgame", [
            "/comics/DC New 52/Action Comics/Action Comics 001.cbz"
        ]))

    def test_plan_moves_oneshot_only(self) -> None:
        volumes = [
            {
                "id": 6,
                "title": "Batgirl: Endgame",
                "year": 2015,
                "folder": "/comics/DC New 52",
                "issue_count": 1,
            },
            {
                "id": 62,
                "title": "Suicide Squad",
                "year": 1987,
                "folder": "/comics/dc rebirth",
                "issue_count": 67,
            },
        ]
        loose = {"/comics/dc new 52": self.FILES, "/comics/dc rebirth": []}
        plan = kf.plan_imprint_fix(volumes, loose)
        oneshot = next(item for item in plan if item["id"] == 6)
        squad = next(item for item in plan if item["id"] == 62)
        self.assertTrue(oneshot["move_from"].endswith("Batgirl - Endgame.cbz"))
        self.assertIsNone(squad["move_from"])
        self.assertEqual(squad["to_folder"], "/comics/dc rebirth/Suicide Squad (1987)")
        leftover_plan = kf.plan_imprint_fix(
            [
                {
                    "id": 37,
                    "title": "DC Rebirth Omnibus",
                    "year": 2016,
                    "folder": "/comics/dc rebirth",
                    "issue_count": 1,
                    "issues_downloaded": 0,
                }
            ],
            {"/comics/dc rebirth": []},
        )
        self.assertEqual(leftover_plan, [])


if __name__ == "__main__":
    unittest.main()
