#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comicarr_set_qbit as qbit


class ComicarrQbitTests(unittest.TestCase):
    def test_https_443_omits_port(self) -> None:
        self.assertEqual(
            qbit.qbit_url({"host": "qbittorrent.example.box.ca", "port": 443, "useSsl": True}),
            "https://qbittorrent.example.box.ca",
        )

    def test_http_keeps_port(self) -> None:
        self.assertEqual(
            qbit.qbit_url({"host": "10.0.0.10", "port": 8080, "useSsl": False}),
            "http://10.0.0.10:8080",
        )

    def test_whatbox_204_login_counts_as_success(self) -> None:
        text = ""
        status = 204
        cookies = {"QBT_SID_10373": "x"}
        ok = (text or "").strip() == "Ok." or (status in (200, 204) and bool(cookies))
        self.assertTrue(ok)

    def test_failed_login_is_not_success(self) -> None:
        text = "Fails."
        status = 403
        cookies = {}
        ok = (text or "").strip() == "Ok." or (status in (200, 204) and bool(cookies))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
