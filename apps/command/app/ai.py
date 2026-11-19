from __future__ import annotations

import base64

import httpx

from app.config import settings


def _generate(prompt: str, images: list[bytes] | None = None) -> tuple[str | None, str]:
    if not settings.ollama_base_url:
        return None, "No local model is configured."
    model = settings.ollama_vision_model if images else settings.ollama_text_model
    if not model:
        return None, "No local model name is configured."
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if images:
        payload["images"] = [base64.b64encode(blob).decode() for blob in images]
    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(f"{settings.ollama_base_url.rstrip('/')}/api/generate", json=payload)
    except httpx.HTTPError as exc:
        return None, exc.__class__.__name__
    if response.status_code >= 400:
        return None, f"HTTP {response.status_code}"
    body = response.json()
    text = (body.get("response") or "").strip()
    if not text:
        return None, "The model returned an empty response."
    return text, model


def review_draft(author: str, rating: float, body: str) -> dict:
    prompt = (
        "Write a short reply from Survey Café in Bonita Springs to this guest review. "
        "Do not invent dishes, staff names, or compensation. If the review is unhappy, apologize and invite them to talk to the manager. "
        f"Rating: {rating}. Author: {author or 'Guest'}. Review: {body}"
    )
    text, model = _generate(prompt)
    if text is None:
        rating_text = f"{rating:g}" if rating else "their"
        draft = (
            f"Thank you for taking the time to write about your visit"
            f"{f', {author}' if author else ''}. "
            f"We read every {rating_text}-star note. "
            "If there is anything we should make right, please ask for the manager on your next visit or call the restaurant."
        )
        return {
            "text": draft,
            "source": "template",
            "detail": "No local model is configured. This is a fill-in draft, not a model response.",
        }
    return {"text": text, "source": "ollama", "detail": f"Drafted by {model}. Review it before sending."}


def event_promo(name: str, kind: str, starts_at: str, description: str) -> dict:
    prompt = (
        "Write a short social caption and a short email blurb for a Survey Café event. "
        "Do not invent prices, menus, or ticket links that are not in the description. "
        f"Event: {name}. Kind: {kind}. When: {starts_at}. Details: {description}"
    )
    text, model = _generate(prompt)
    if text is None:
        when = f" on {starts_at}" if starts_at else ""
        draft = (
            f"{name}{when} at Survey Café. {description.strip()} "
            "Ask the restaurant for the details before this is posted."
        ).strip()
        return {
            "text": draft,
            "source": "template",
            "detail": "No local model is configured. This is a fill-in caption, not a model response.",
        }
    return {"text": text, "source": "ollama", "detail": f"Drafted by {model}."}


def read_menu_image(blob: bytes) -> tuple[str | None, str]:
    if not settings.ollama_vision_model:
        return None, "No vision model is configured. The image is stored and was not read."
    prompt = (
        "Read this restaurant menu. Return only a JSON array of objects with name, description, and price. "
        "Price is a number of dollars. Omit anything you cannot read. Do not invent items."
    )
    return _generate(prompt, images=[blob])
