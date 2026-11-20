#!/usr/bin/env python3
"""Make MAUTIC_TRUSTED_PROXIES a JSON array in one env file.

Direct Tailscale access uses []. A bare CIDR is not JSON and Mautic refuses
to start. This rewrites that one line. It does not print the value, rewrite
other keys, or recreate a container.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _raw(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _json_list(value: str) -> bool:
    try:
        parsed = json.loads(_raw(value))
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: fix-mautic-trusted-proxies.py /path/to/.env", file=sys.stderr)
        return 1
    path = Path(sys.argv[1])
    if path.is_symlink():
        print("Refusing: env file is a symlink. Nothing was written.")
        return 1
    if not path.is_file():
        print("Refusing: env file is missing. Nothing was written.")
        return 1
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    found = False
    changed = False
    output: list[str] = []
    for line in lines:
        if line.startswith("MAUTIC_TRUSTED_PROXIES="):
            found = True
            value = line.split("=", 1)[1]
            if _json_list(value):
                output.append(line)
            else:
                output.append("MAUTIC_TRUSTED_PROXIES='[]'")
                changed = True
        else:
            output.append(line)
    if not found:
        output.append("MAUTIC_TRUSTED_PROXIES='[]'")
        changed = True
    text = "\n".join(output) + "\n"
    if changed and text != original:
        path.write_text(text, encoding="utf-8")
        print("corrected")
    else:
        print("kept")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
