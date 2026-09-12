#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comicarr_index as idx


class ComicarrIndexTests(unittest.TestCase):
    def test_collect_unwraps_imprints_to_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            series = root / "DC Comics" / "Action Comics (1938)"
            series.mkdir(parents=True)
            (series / "001.cbz").write_bytes(b"x")
            mixed = root / "dc rebirth"
            mixed.mkdir()
            (mixed / "loose.cbr").write_bytes(b"x")
            batman = mixed / "Batman"
            batman.mkdir()
            (batman / "001.cbz").write_bytes(b"x")
            nightwing = mixed / "Nightwing"
            nightwing.mkdir()
            (nightwing / "001.cbz").write_bytes(b"x")
            empty = root / "Panini Verlag"
            empty.mkdir()

            found = {path.name for path in idx.collect(root)}
            self.assertEqual(found, {"Action Comics (1938)", "Batman", "Nightwing"})

    def test_index_uses_leaf_names_and_file_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "comics"
            scan = root / ".comicarr-scan"
            series = root / "DC Comics" / "Action Comics (1938)"
            series.mkdir(parents=True)
            (series / "001.cbz").write_bytes(b"x")
            (series / "nested").mkdir()
            (series / "nested" / "002.cbz").write_bytes(b"x")

            result = idx.index_root(root, scan)
            dest = scan / "Action Comics (1938)"
            self.assertEqual(result["series"], 1)
            self.assertEqual(result["files"], 2)
            self.assertTrue(dest.is_dir())
            self.assertFalse(dest.is_symlink())
            self.assertTrue((dest / "001.cbz").is_symlink())
            self.assertEqual((dest / "001.cbz").resolve(), series / "001.cbz")
            self.assertEqual((dest / idx.SOURCE_MARKER).read_text().strip(), str(series.resolve()))

    def test_label_disambiguates_collisions(self) -> None:
        used: set[str] = set()
        first = idx.series_label(Path("/comics/DC Comics/Batman"), Path("/comics"), used)
        second = idx.series_label(Path("/comics/dc rebirth/Batman"), Path("/comics"), used)
        self.assertEqual(first, "Batman")
        self.assertEqual(second, "Batman [dc rebirth]")


if __name__ == "__main__":
    unittest.main()
