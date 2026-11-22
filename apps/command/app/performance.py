"""Marketing performance for one date window.

Every number here is computed from stored records. A missing source stays
unavailable. A contact total is never returned as new contacts, and a
scheduled post is never returned as a published post.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.jsonutil import load
from app.models import AdSnapshot, Campaign, Event, MetricSample, Review, SocialPost


def parse_window(now: datetime, days: int | None, start: str, end: str) -> tuple[datetime, datetime]:
    if days is not None:
        if days not in {7, 30, 90}:
            raise ValueError("Choose 7, 30, or 90 days.")
        finish = now
        begin = now - timedelta(days=days)
        return begin, finish
    if not start or not end:
        raise ValueError("A custom range needs a start and an end date.")
    begin = _date(start)
    finish = _date(end) + timedelta(days=1)
    if finish <= begin:
        raise ValueError("The end date has to be after the start date.")
    if finish - begin > timedelta(days=366):
        raise ValueError("A custom range cannot be longer than 366 days.")
    return begin, finish


def from_db(db: Session, start: datetime, end: datetime) -> dict:
    now = datetime.now(timezone.utc)
    ads = [
        {
            "platform": row.platform,
            "campaign_name": row.campaign_name,
            "spend_cents": row.spend_cents,
            "clicks": row.clicks,
            "captured_at": _aware(row.captured_at),
        }
        for row in db.query(AdSnapshot).all()
    ]
    posts = []
    for row in db.query(SocialPost).all():
        posts.append(
            {
                "id": row.id,
                "body": row.body,
                "status": row.status,
                "detail": row.detail,
                "scheduled_for": row.scheduled_for,
                "updated_at": _aware(row.updated_at),
                "channels": load(row.channels_json, []),
                "analytics": load(getattr(row, "analytics_json", "{}") or "{}", {}),
            }
        )
    reviews = [
        {
            "id": row.id,
            "platform": row.platform,
            "source": row.source,
            "author": row.author,
            "rating": row.rating,
            "body": row.body,
            "reviewed_at": row.reviewed_at,
            "approval": row.approval,
            "publish_state": row.publish_state,
        }
        for row in db.query(Review).all()
    ]
    campaigns = [{"id": row.id, "name": row.name, "status": row.status} for row in db.query(Campaign).all()]
    events = [{"name": row.name, "starts_at": row.starts_at, "status": row.status} for row in db.query(Event).all()]
    samples = [
        {"metric": row.metric, "value": row.value, "captured_at": _aware(row.captured_at)}
        for row in db.query(MetricSample).all()
    ]
    return report(
        now=now,
        start=start,
        end=end,
        ads=ads,
        posts=posts,
        reviews=reviews,
        campaigns=campaigns,
        events=events,
        samples=samples,
    )


def previous_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    return start - (end - start), start


def report(
    *,
    now: datetime,
    start: datetime,
    end: datetime,
    ads: list[dict],
    posts: list[dict],
    reviews: list[dict],
    campaigns: list[dict],
    events: list[dict],
    samples: list[dict],
) -> dict:
    prior_start, prior_end = previous_window(start, end)
    current_ads = _latest_ads(ads, start, end)
    prior_ads = _latest_ads(ads, prior_start, prior_end)
    spend = _metric_spend(current_ads, prior_ads, ads, start)
    new_contacts = _metric_new_contacts(samples)
    revenue = _unavailable(
        "attributed_revenue",
        "Marketing-attributed revenue",
        "usd",
        "No reservation or point-of-sale attribution is connected.",
        "Revenue is not estimated from covers, events, or ad clicks.",
    )
    roi = _unavailable(
        "roi",
        "Marketing ROI",
        "ratio",
        "Marketing-attributed revenue and advertising spend.",
        "ROI is not calculated. Revenue is unavailable, so spend alone is not a return.",
    )
    reservations = _unavailable(
        "reservations",
        "Attributable reservations",
        "count",
        "No reservation source is connected.",
        "Events stored here are not reservations.",
    )
    audience = _audience(samples, start, end, prior_start, prior_end)
    return {
        "generated_at": _stamp(now),
        "start": _stamp(start),
        "end": _stamp(end),
        "previous_start": _stamp(prior_start),
        "previous_end": _stamp(prior_end),
        "kpis": [reservations, spend, new_contacts, revenue, roi],
        "charts": [
            _spend_chart(ads, start, end),
            _click_chart(ads, start, end),
            {
                "id": "reservations",
                "label": "Reservations",
                "status": "unavailable",
                "series": "none",
                "points": [],
                "source": "No reservation source is connected.",
                "refreshed_at": None,
                "detail": "No reservation observations are stored.",
            },
            audience["chart"],
        ],
        "channels": _channels(current_ads, posts, reviews, start, end),
        "content": _content(posts, start, end),
        "reputation": _reputation(reviews, start, end),
        "actions": _actions(posts, reviews, campaigns, events, now),
        "blockers": [
            "Temporal must report healthy from its cluster health command before Phase 3 is deployed. A running container is not enough.",
            "Postiz homepage reachability is not a passed public API authentication test. Social metrics stay incomplete until that call succeeds.",
        ],
    }


def _metric_spend(current: list[dict], prior: list[dict], ads: list[dict], start: datetime) -> dict:
    if current:
        value = sum(int(row["spend_cents"]) for row in current)
        refreshed = max(row["captured_at"] for row in current)
        comparison = None
        if prior:
            previous = sum(int(row["spend_cents"]) for row in prior)
            comparison = _comparison(value, previous, None)
        return _actual(
            "ad_spend",
            "Advertising spend",
            "cents",
            value,
            "Latest stored Google Ads or Meta report for each campaign in this range.",
            refreshed,
            "These reports are not added across days. A missing platform is omitted, not treated as zero.",
            comparison,
        )
    newest = _newest(ads, "captured_at")
    if newest is not None and newest < start:
        return _stale(
            "ad_spend",
            "Advertising spend",
            "cents",
            "Latest stored Google Ads or Meta report for each campaign in this range.",
            newest,
            "The newest advertising report is older than this range.",
        )
    return _unavailable(
        "ad_spend",
        "Advertising spend",
        "cents",
        "Google Ads or Meta Ads reports stored by Sync.",
        "No advertising report is stored.",
    )


def _metric_new_contacts(samples: list[dict]) -> dict:
    totals = [row for row in samples if row["metric"] == "mautic_contact_total"]
    detail = "Mautic's contact total is not a count of new contacts. No date-bounded new-contact figure is stored."
    refreshed = _newest(totals, "captured_at") if totals else None
    return {
        "id": "new_contacts",
        "label": "New contacts",
        "status": "unavailable",
        "value": None,
        "unit": "count",
        "source": "Mautic contact total is a separate reading and is not used here.",
        "refreshed_at": _stamp(refreshed) if refreshed else None,
        "detail": detail,
        "comparison": None,
    }


def _audience(samples: list[dict], start: datetime, end: datetime, prior_start: datetime, prior_end: datetime) -> dict:
    points = _samples(samples, "mautic_contact_total", start, end)
    prior = _samples(samples, "mautic_contact_total", prior_start, prior_end)
    if len(points) >= 2:
        comparison = None
        if prior:
            comparison = _comparison(points[-1]["value"], prior[-1]["value"], "up")
        chart = {
            "id": "audience",
            "label": "Mautic contact total",
            "status": "actual",
            "series": "line",
            "points": points,
            "source": "Stored Mautic contact totals from Refresh. Not new contacts.",
            "refreshed_at": points[-1]["at"],
            "detail": "The line is the stored contact total. It is not audience growth of new subscribers.",
            "comparison": comparison,
        }
    elif len(points) == 1:
        chart = {
            "id": "audience",
            "label": "Mautic contact total",
            "status": "incomplete",
            "series": "none",
            "points": points,
            "source": "Stored Mautic contact totals from Refresh. Not new contacts.",
            "refreshed_at": points[-1]["at"],
            "detail": "One stored total is not enough to show a change.",
            "comparison": None,
        }
    else:
        chart = {
            "id": "audience",
            "label": "Mautic contact total",
            "status": "unavailable",
            "series": "none",
            "points": [],
            "source": "Stored Mautic contact totals from Refresh. Not new contacts.",
            "refreshed_at": None,
            "detail": "No Mautic contact total has been stored for this range.",
            "comparison": None,
        }
    return {"chart": chart}


def _spend_chart(ads: list[dict], start: datetime, end: datetime) -> dict:
    points = [
        {"at": _stamp(row["captured_at"]), "value": int(row["spend_cents"]), "label": row["platform"]}
        for row in ads
        if start <= row["captured_at"] < end
    ]
    points.sort(key=lambda row: row["at"])
    if not points:
        return {
            "id": "ad_spend",
            "label": "Advertising reports",
            "status": "unavailable",
            "series": "none",
            "points": [],
            "source": "Stored advertising reports.",
            "refreshed_at": None,
            "detail": "No advertising report was captured in this range.",
        }
    return {
        "id": "ad_spend",
        "label": "Advertising reports",
        "status": "actual",
        "series": "points",
        "points": points,
        "source": "Each point is one stored report, in cents. Points are not a daily spend total.",
        "refreshed_at": points[-1]["at"],
        "detail": "Reports captured on different days are not added together in this chart.",
    }


def _click_chart(ads: list[dict], start: datetime, end: datetime) -> dict:
    points = [
        {"at": _stamp(row["captured_at"]), "value": int(row["clicks"]), "label": row.get("campaign_name") or row["platform"]}
        for row in ads
        if start <= row["captured_at"] < end
    ]
    points.sort(key=lambda row: row["at"])
    if not points:
        return {
            "id": "campaign_performance",
            "label": "Campaign clicks",
            "status": "unavailable",
            "series": "none",
            "points": [],
            "source": "Clicks on stored advertising reports.",
            "refreshed_at": None,
            "detail": "No campaign click report was captured in this range. Email opens are not included.",
        }
    return {
        "id": "campaign_performance",
        "label": "Campaign clicks",
        "status": "actual",
        "series": "points",
        "points": points,
        "source": "Clicks on stored advertising reports. Email opens are not included.",
        "refreshed_at": points[-1]["at"],
        "detail": "A zero is a reported click count. A missing report is not drawn as zero.",
    }


def _channels(ads: list[dict], posts: list[dict], reviews: list[dict], start: datetime, end: datetime) -> list[dict]:
    google_reviews = _dated(reviews, start, end, lambda row: row["source"] == "google")
    return [
        _review_channel("google_business", "Google Business Profile", google_reviews, "Google reviews stored from an authorized pull."),
        _ads_channel("google_ads", "Google Ads", [row for row in ads if row["platform"] == "google_ads"]),
        _post_channel("facebook", "Facebook", posts, "facebook", start, end),
        _post_channel("instagram", "Instagram", posts, "instagram", start, end),
        _post_channel("tiktok", "TikTok", posts, "tiktok", start, end),
        {
            "id": "mautic_email",
            "label": "Mautic email",
            "status": "unavailable",
            "value": None,
            "unit": "count",
            "source": "Mautic campaign statistics.",
            "refreshed_at": None,
            "detail": "Sends, opens, and clicks are not stored. Drafts on the Marketing page are not sends.",
            "comparison": None,
        },
    ]


def _engagement_score(item: dict) -> int:
    if isinstance(item.get("engagement"), (int, float)):
        return int(item["engagement"])
    return int(item.get("likes") or 0)


def _content(posts: list[dict], start: datetime, end: datetime) -> dict:
    scheduled = []
    published = []
    engagement = []
    for row in posts:
        when = _parse_stamp(row.get("scheduled_for") or "")
        updated = row.get("updated_at")
        providers = [str(item.get("provider") or "") for item in row.get("channels") or []]
        if row["status"] in {"draft", "submitted"} and when is not None and start <= when < end:
            scheduled.append(row)
        if row["status"] == "published" and isinstance(updated, datetime) and start <= updated < end:
            published.append(row)
        stats = row.get("analytics") or {}
        if row["status"] == "published" and any(isinstance(stats.get(key), (int, float)) for key in ("likes", "comments", "impressions", "reach", "engagement")):
            if isinstance(updated, datetime) and start <= updated < end:
                engagement.append(stats)
    engagement_value = None
    engagement_status = "unavailable"
    engagement_detail = "Postiz responses stored here do not include likes, comments, impressions, or reach."
    scored = [
        item
        for item in engagement
        if isinstance(item.get("engagement"), (int, float)) or isinstance(item.get("likes"), (int, float))
    ]
    if scored:
        engagement_status = "actual"
        engagement_value = sum(_engagement_score(item) for item in scored)
        engagement_detail = "Sum of likes or engagement figures Postiz included on published posts in this range."
    elif engagement:
        engagement_status = "incomplete"
        engagement_detail = "Postiz included impressions, reach, or comments, but not a likes or engagement total. Those fields are not converted into a score."
    return {
        "scheduled": _count_metric(
            "scheduled_posts",
            "Scheduled posts",
            len(scheduled),
            "Posts stored here as drafts or submissions with a schedule in this range. These are not published posts.",
            "actual",
        ),
        "published": _count_metric(
            "published_posts",
            "Published posts",
            len(published),
            "Posts stored here whose status is published and whose last update is in this range.",
            "actual" if published else "unavailable",
            none_when_empty=not published,
        ),
        "engagement": {
            "id": "engagement",
            "label": "Post engagement",
            "status": engagement_status,
            "value": engagement_value,
            "unit": "count",
            "source": "Engagement fields on Postiz post responses.",
            "refreshed_at": None,
            "detail": engagement_detail,
            "comparison": None,
        },
    }


def _reputation(reviews: list[dict], start: datetime, end: datetime) -> dict:
    authorized = _dated(reviews, start, end, lambda row: row["source"] in {"google", "yelp"})
    undated = [
        row
        for row in reviews
        if row["source"] in {"google", "yelp"} and _parse_stamp(row.get("reviewed_at") or "") is None
    ]
    if not authorized:
        status = "incomplete" if undated else "unavailable"
        detail = (
            f"{len(undated)} authorized reviews have no date and are left out of this range."
            if undated
            else "No authorized Google or Yelp reviews with a date are stored. Manual notes are not included."
        )
        return {
            "status": status,
            "count": None,
            "average_rating": None,
            "unresolved_negative": None,
            "source": "Google Business Profile and Yelp pulls. Manual notes are excluded.",
            "refreshed_at": None,
            "detail": detail,
            "reviews": [],
        }
    ratings = [float(row["rating"]) for row in authorized]
    negative = [
        row
        for row in authorized
        if float(row["rating"]) <= 3 and row.get("publish_state") != "sent"
    ]
    return {
        "status": "actual",
        "count": len(authorized),
        "average_rating": round(sum(ratings) / len(ratings), 2),
        "unresolved_negative": len(negative),
        "source": "Google Business Profile and Yelp pulls. Manual notes are excluded.",
        "refreshed_at": None,
        "detail": "Unresolved means rated 3 or below and no reply has been sent.",
        "reviews": [
            {
                "platform": row["source"],
                "author": row.get("author") or "",
                "rating": row["rating"],
                "body": row.get("body") or "",
            }
            for row in authorized[:8]
        ],
    }


def _actions(posts, reviews, campaigns, events, now: datetime) -> dict:
    upcoming = []
    for row in events:
        when = _parse_stamp(row.get("starts_at") or "")
        if when is not None and when >= now:
            upcoming.append({"name": row["name"], "starts_at": _stamp(when), "status": row.get("status") or ""})
    return {
        "scope": "Open items on this server. The date range does not hide them.",
        "failed_posts": [
            {"id": row["id"], "body": row.get("body") or "", "detail": row.get("detail") or ""}
            for row in posts
            if row["status"] == "error"
        ],
        "pending_reviews": [
            {"id": row["id"], "platform": row.get("platform") or row.get("source") or "", "body": row.get("body") or ""}
            for row in reviews
            if row.get("approval") == "pending"
        ],
        "unsent_drafts": [
            {"id": row["id"], "name": row["name"], "status": row["status"]}
            for row in campaigns
            if row["status"] in {"local", "mautic_draft"}
        ],
        "upcoming_events": upcoming,
    }


def _review_channel(metric_id: str, label: str, rows: list[dict], source: str) -> dict:
    if not rows:
        return _unavailable(metric_id, label, "count", source, "No dated reviews from this source are stored in the range.")
    return _actual(
        metric_id,
        label,
        "count",
        len(rows),
        source,
        None,
        "Count of dated reviews stored from that source. Manual notes are not included.",
        None,
    )


def _ads_channel(metric_id: str, label: str, rows: list[dict]) -> dict:
    if not rows:
        return _unavailable(metric_id, label, "cents", "Stored Google Ads reports.", "No Google Ads report is stored in this range.")
    return _actual(
        metric_id,
        label,
        "cents",
        sum(int(row["spend_cents"]) for row in rows),
        "Latest stored Google Ads report for each campaign in this range.",
        max(row["captured_at"] for row in rows),
        "Clicks on those same reports are in the campaign chart.",
        None,
    )


def _post_channel(metric_id: str, label: str, posts: list[dict], provider: str, start: datetime, end: datetime) -> dict:
    matched = []
    for row in posts:
        providers = {str(item.get("provider") or "") for item in row.get("channels") or []}
        if provider not in providers and not (provider == "instagram" and "instagram-standalone" in providers):
            continue
        updated = row.get("updated_at")
        if row["status"] == "published" and isinstance(updated, datetime) and start <= updated < end:
            matched.append(row)
    if not matched:
        return _unavailable(
            metric_id,
            label,
            "count",
            "Published posts stored here for this Postiz channel.",
            "No published post for this channel is stored in the range. A scheduled draft is not counted.",
        )
    return _count_metric(
        metric_id,
        label,
        len(matched),
        "Published posts stored here for this Postiz channel. Engagement is separate and stays empty unless Postiz sent it.",
        "actual",
    )


def _count_metric(metric_id: str, label: str, value: int, source: str, status: str, none_when_empty: bool = False) -> dict:
    if none_when_empty and value == 0:
        return _unavailable(metric_id, label, "count", source, "None are stored in this range.")
    return {
        "id": metric_id,
        "label": label,
        "status": status,
        "value": value,
        "unit": "count",
        "source": source,
        "refreshed_at": None,
        "detail": source,
        "comparison": None,
    }


def _latest_ads(rows: list[dict], start: datetime, end: datetime) -> list[dict]:
    chosen: dict[tuple, dict] = {}
    for row in rows:
        if not (start <= row["captured_at"] < end):
            continue
        key = (row["platform"], row.get("campaign_name") or "")
        current = chosen.get(key)
        if current is None or row["captured_at"] >= current["captured_at"]:
            chosen[key] = row
    return list(chosen.values())


def _samples(samples: list[dict], metric: str, start: datetime, end: datetime) -> list[dict]:
    rows = [row for row in samples if row["metric"] == metric and start <= row["captured_at"] < end]
    rows.sort(key=lambda row: row["captured_at"])
    return [{"at": _stamp(row["captured_at"]), "value": int(row["value"])} for row in rows]


def _dated(rows: list[dict], start: datetime, end: datetime, pred) -> list[dict]:
    chosen = []
    for row in rows:
        if not pred(row):
            continue
        when = _parse_stamp(row.get("reviewed_at") or "")
        if when is not None and start <= when < end:
            chosen.append(row)
    return chosen


def _comparison(current: int, previous: int, favorable: str | None) -> dict:
    delta = current - previous
    tone = "neutral"
    if favorable == "up" and delta > 0:
        tone = "good"
    elif favorable == "up" and delta < 0:
        tone = "bad"
    elif favorable == "down" and delta > 0:
        tone = "bad"
    elif favorable == "down" and delta < 0:
        tone = "good"
    return {"previous": previous, "delta": delta, "tone": tone}


def _actual(metric_id, label, unit, value, source, refreshed, detail, comparison) -> dict:
    return {
        "id": metric_id,
        "label": label,
        "status": "actual",
        "value": value,
        "unit": unit,
        "source": source,
        "refreshed_at": _stamp(refreshed) if isinstance(refreshed, datetime) else refreshed,
        "detail": detail,
        "comparison": comparison,
    }


def _unavailable(metric_id, label, unit, source, detail) -> dict:
    return {
        "id": metric_id,
        "label": label,
        "status": "unavailable",
        "value": None,
        "unit": unit,
        "source": source,
        "refreshed_at": None,
        "detail": detail,
        "comparison": None,
    }


def _stale(metric_id, label, unit, source, refreshed: datetime, detail: str) -> dict:
    return {
        "id": metric_id,
        "label": label,
        "status": "stale",
        "value": None,
        "unit": unit,
        "source": source,
        "refreshed_at": _stamp(refreshed),
        "detail": detail,
        "comparison": None,
    }


def _newest(rows: list[dict], key: str) -> datetime | None:
    stamps = [row[key] for row in rows if isinstance(row.get(key), datetime)]
    return max(stamps) if stamps else None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Use a YYYY-MM-DD date.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_stamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()
