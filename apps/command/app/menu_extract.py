from __future__ import annotations

import io
import json
import re

PRICE = re.compile(r"^\$?\d{1,4}(?:\.\d{1,2})?$")


def parse_price(token: str) -> int | None:
    cleaned = token.strip().lstrip("$").replace(",", "")
    if not PRICE.fullmatch(cleaned):
        return None
    cents = int(round(float(cleaned) * 100))
    if cents < 0 or cents > 100_000:
        return None
    return cents


def parse_menu_text(text: str, confidence: str = "parser") -> list[dict]:
    items: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [part.strip() for part in line.split("|")]
            price = parse_price(parts[-1])
            if price is None or len(parts) < 2 or not parts[0]:
                continue
            items.append(
                {
                    "name": parts[0],
                    "description": " | ".join(part for part in parts[1:-1] if part),
                    "price_cents": price,
                    "confidence": confidence,
                }
            )
            continue
        match = re.search(r"^(?P<name>.+?)\s+\$?(?P<price>\d{1,4}(?:\.\d{1,2})?)$", line)
        if not match:
            continue
        price = parse_price(match.group("price"))
        name = match.group("name").strip(" -–—")
        if price is None or not name:
            continue
        items.append(
            {"name": name, "description": "", "price_cents": price, "confidence": confidence}
        )
    return items


def pdf_text(blob: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(blob))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def items_from_model_text(text: str) -> list[dict]:
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            items = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                price = row.get("price_cents")
                if price is None and row.get("price") is not None:
                    price = parse_price(str(row["price"]))
                if not row.get("name") or not isinstance(price, int):
                    continue
                items.append(
                    {
                        "name": str(row["name"]).strip(),
                        "description": str(row.get("description") or "").strip(),
                        "price_cents": price,
                        "confidence": "ollama",
                    }
                )
            if items:
                return items
    return parse_menu_text(text, confidence="ollama")
