#!/usr/bin/env python3
import json
from datetime import datetime, timezone

import requests

API_URL = (
    "https://vision.hack2skill.com/api/v1/innovator/public/event/public-list"
    "?page=1&records=50&search=&start=2024-01-01T00:00:00.000Z&end=2028-01-01T00:00:00.000Z"
)


def _event_link_from_slug(event_url):
    if not event_url:
        return "https://vision.hack2skill.com/hackathons-listing"

    slug = str(event_url).strip().strip("/")
    if not slug:
        return "https://vision.hack2skill.com/hackathons-listing"

    if slug.startswith("event/"):
        slug = slug[len("event/") :]

    return f"https://vision.hack2skill.com/event/{slug}"


def _to_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _status_from_dates(start_raw, end_raw):
    now = datetime.now(timezone.utc)
    try:
        start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00")) if start_raw else None
    except ValueError:
        start_dt = None
    try:
        end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")) if end_raw else None
    except ValueError:
        end_dt = None

    if end_dt and end_dt < now:
        return "closed"
    if not start_dt or start_dt <= now:
        return "open"
    return "open"


def scrape():
    try:
        response = requests.get(
            API_URL,
            timeout=25,
            headers={"User-Agent": "hackathonscraper/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return json.dumps({"error": str(exc), "data": []}, indent=2)

    items = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []

    hackathons = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        event_url = item.get("eventUrl")
        if not title:
            continue

        reg_start = item.get("registrationStart")
        reg_end = item.get("registrationEnd")
        status = _status_from_dates(reg_start, reg_end)

        mode_raw = str(item.get("mode") or "VIRTUAL").upper()
        if "HYBRID" in mode_raw:
            mode = "hybrid"
        elif "IN_PERSON" in mode_raw or "OFFLINE" in mode_raw:
            mode = "in_person"
        else:
            mode = "virtual"

        hackathons.append(
            {
                "name": title,
                "location": mode,
                "desc": item.get("participation") or "",
                "date": {
                    "start": _to_iso(reg_start),
                    "end": _to_iso(reg_end),
                },
                "logo": item.get("thumbnail") or "",
                "status": status,
                "link": _event_link_from_slug(event_url),
            }
        )

    return json.dumps(hackathons, sort_keys=True, indent=2)


def jsondump():
    with open("hackathons.JSON", "w", encoding="utf-8") as f:
        f.write(scrape())
