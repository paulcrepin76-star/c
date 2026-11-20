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
    check_only = False
    args = sys.argv[1:]
    if args and args[0] == "--check":
        check_only = True
        args = args[1:]
    if len(args) != 1:
        print("Usage: fix-mautic-trusted-proxies.py [--check] /path/to/.env", file=sys.stderr)
        return 1
    path = Path(args[0])
    if path.is_symlink():
        print("Refusing: env file is a symlink. Nothing was written.")
        return 1
    if not path.is_file():
        print("Refusing: env file is missing. Nothing was written.")
        return 1
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    found = 0
    valid = 0
    changed = False
    output: list[str] = []
    for line in lines:
        if line.startswith("MAUTIC_TRUSTED_PROXIES="):
            found += 1
            value = line.split("=", 1)[1]
            if _json_list(value):
                valid += 1
                output.append(line)
            else:
                output.append("MAUTIC_TRUSTED_PROXIES='[]'")
                changed = True
        else:
            output.append(line)
    if found == 0:
        output.append("MAUTIC_TRUSTED_PROXIES='[]'")
        changed = True
    if check_only:
        print("valid" if found == 1 and valid == 1 else "invalid")
        return 0
    text = "\n".join(output) + "\n"
    if changed and text != original:
        path.write_text(text, encoding="utf-8")
        print("corrected")
    else:
        print("kept")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
