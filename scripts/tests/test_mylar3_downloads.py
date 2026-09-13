#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mylar3_config as mc
import mylar3_downloads as md


class ExtraTests(unittest.TestCase):
    def test_skips_nyaa_and_splits_newznab_from_torznab(self) -> None:
        indexers = [
            {"Id": 1, "Name": "NZBgeek", "Implementation": "Newznab", "Enable": True},
            {"Id": 3, "Name": "Nyaa.si", "Implementation": "Cardigann", "Enable": True},
            {"Id": 7, "Name": "Torrent9", "Implementation": "Cardigann", "Enable": True},
            {"Id": 9, "Name": "Nyaa Manga English", "Implementation": "Cardigann", "Enable": True},
        ]
        newznabs, torznabs = md.extras_from_prowlarr(indexers, "secret-prowlarr-key")
        self.assertEqual(len(newznabs), 1)
        self.assertEqual(len(torznabs), 1)
        self.assertEqual(newznabs[0][0], "NZBgeek")
        self.assertEqual(newznabs[0][1], "http://prowlarr:9696/1/api")
        self.assertEqual(newznabs[0][4], "7030")
        self.assertEqual(torznabs[0][0], "Torrent9")
        self.assertEqual(torznabs[0][1], "http://prowlarr:9696/7/api")
        self.assertEqual(torznabs[0][4], "")
        dumped = json.dumps(md.flatten_extras(newznabs + torznabs))
        self.assertIn("secret-prowlarr-key", dumped)


class ApplyDownloadsTests(unittest.TestCase):
    def test_enables_getcomics_and_house_clients_not_jdownloader(self) -> None:
        cfg = mc.load_ini(Path("/tmp/does-not-exist.ini"))
        mc.apply_safe_defaults(cfg)
        md.apply_download_clients(
            cfg,
            sab={"apiKey": "sab-secret"},
            qbit={
                "host": "qbittorrent.example.box.ca",
                "port": 443,
                "useSsl": True,
                "username": "deicide",
                "password": "qbit-secret",
            },
            newznabs=[("NZBgeek", "http://prowlarr:9696/1/api", "p-key", "1", "7030", "1", 1)],
            torznabs=[("Torrent9", "http://prowlarr:9696/7/api", "p-key", "1", "", "1", 2)],
        )
        data = md.download_summary(cfg)
        self.assertTrue(data["enable_ddl"])
        self.assertTrue(data["enable_getcomics"])
        self.assertFalse(data["jd2_enable"])
        self.assertTrue(data["enable_flaresolverr"])
        self.assertEqual(data["flaresolverr_url"], "http://flaresolverr:8191")
        self.assertTrue(data["has_sab_host"])
        self.assertTrue(data["has_qbit_host"])
        self.assertEqual(data["nzb_downloader"], "0")
        self.assertEqual(data["torrent_downloader"], "5")
        self.assertEqual(data["sab_category"], "comics")
        self.assertEqual(data["qbit_label"], "comics")
        self.assertEqual(data["qbit_folder"], "/home/deicide/Downloads/comics")
        self.assertEqual(data["newznab_providers"], 1)
        self.assertEqual(data["torznab_providers"], 1)
        self.assertTrue(data["move_files"])
        self.assertFalse(data["rename_files"])
        self.assertFalse(data["imp_move"])
        self.assertFalse(data["imp_rename"])
        self.assertFalse(data["autowant_all"])
        self.assertFalse(data["autowant_upcoming"])
        dumped = json.dumps(data)
        self.assertNotIn("sab-secret", dumped)
        self.assertNotIn("qbit-secret", dumped)
        self.assertNotIn("p-key", dumped)
        self.assertNotIn("qbittorrent.example.box.ca", dumped)
        self.assertEqual(md.qbit_url({"host": "qbittorrent.example.box.ca", "port": 443, "useSsl": True}), "https://qbittorrent.example.box.ca")


class DownloadScriptTests(unittest.TestCase):
    def test_script_does_not_enable_jdownloader_or_autowant(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "mylar3-downloads.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("Mylar3 was removed. Do not reinstall unless asked.", text)
        self.assertIn("Does not enable JDownloader", text)
        self.assertIn("Does not start Comicarr", text)
        self.assertIn("Does not send imp_move", text)
        self.assertIn("action=massimport", text)
        self.assertNotIn("imp_move=0", text)
        self.assertNotIn("docker start comicarr", text)
        self.assertIn("JDownloader was enabled. Refusing to restart.", text)
        self.assertIn("Search + Want All", text)


if __name__ == "__main__":
    unittest.main()
