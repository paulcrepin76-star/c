#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "flaresolverr-attach.sh"


class FlareSolverrAttachTests(unittest.TestCase):
    def test_attaches_kapowarr_and_prowlarr_networks(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("docker network connect kapowarr_default flaresolverr", text)
        self.assertIn("docker network connect media-net flaresolverr", text)
        self.assertNotIn("0.0.0.0:8191", text)


if __name__ == "__main__":
    unittest.main()
