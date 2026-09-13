#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mylar3_config as mc

SAMPLE = """
[General]
destination_dir = None
rename_files = True
move_files = True
folder_format = $Series ($Year)
file_format = $Series $Annual $Issue ($Year)

[Perms]
enforce_perms = True

[Import]
add_comics = True
imp_rename = True
imp_move = True

[API]
api_enabled = False
api_key = None

[CV]
comicvine_api = None

[DDL]
ddl_location = None
"""


class Mylar3ConfigTests(unittest.TestCase):
    def test_apply_points_at_comics_and_turns_rename_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / "config.ini"
            ini.write_text(SAMPLE, encoding="utf-8")
            cv = root / "cv.key"
            cv.write_text("cv-test-key-123\n", encoding="utf-8")
            out = root / "api.key"
            data = mc.apply(ini, comicvine_file=cv, api_key_out=out)
            text = ini.read_text(encoding="utf-8")
            self.assertEqual(data["destination_dir"], "/comics")
            self.assertEqual(data["ddl_location"], "/downloads")
            self.assertFalse(data["rename_files"])
            self.assertFalse(data["move_files"])
            self.assertFalse(data["enforce_perms"])
            self.assertFalse(data["add_comics"])
            self.assertFalse(data["imp_rename"])
            self.assertFalse(data["imp_move"])
            self.assertTrue(data["api_enabled"])
            self.assertTrue(data["has_api_key"])
            self.assertTrue(data["has_comicvine_api"])
            self.assertEqual(data["folder_format"], "$Series ($Year)")
            self.assertEqual(data["file_format"], "$Series ($Year) #$Issue")
            self.assertIn("destination_dir = /comics", text)
            self.assertIn("rename_files = False", text)
            self.assertIn("enforce_perms = False", text)
            self.assertNotIn("cv-test-key-123", json.dumps(data))
            self.assertTrue(out.is_file())
            self.assertGreaterEqual(len(out.read_text(encoding="utf-8").strip()), 16)

    def test_dollar_folder_tokens_are_not_interpolated(self) -> None:
        cfg = mc.load_ini(Path("/tmp/does-not-exist.ini"))
        mc.apply_safe_defaults(cfg)
        self.assertEqual(cfg.get("General", "folder_format"), "$Series ($Year)")
        self.assertEqual(cfg.get("General", "file_format"), "$Series ($Year) #$Issue")

    def test_summary_omits_secret_values(self) -> None:
        cfg = mc.load_ini(Path("/tmp/does-not-exist.ini"))
        mc.apply_safe_defaults(cfg, comicvine="super-secret-cv", api_key="super-secret-api")
        dumped = json.dumps(mc.summary(cfg))
        self.assertNotIn("super-secret-cv", dumped)
        self.assertNotIn("super-secret-api", dumped)
        self.assertNotIn("super-secret", dumped)
        self.assertIn('"has_comicvine_api": true', dumped)


if __name__ == "__main__":
    unittest.main()
