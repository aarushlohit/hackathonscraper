#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone

import requests

HACK2SKILL_API_URL = (
    "https://vision.hack2skill.com/api/v1/innovator/public/event/public-list"
    "?page=1&records=50&search=&start=2024-01-01T00:00:00.000Z&end=2028-01-01T00:00:00.000Z"
)
DEVPOST_API_URL = "https://devpost.com/api/hackathons"
UNSTOP_API_URL = "https://unstop.com/api/public/opportunity/search-result"


def _event_link_from_slug(event_url):
    if not event_url:
        return "https://vision.hack2skill.com/hackathons-listing"

    slug = str(event_url).strip().strip("/")
    if not slug:
        return "https://vision.hack2skill.com/hackathons-listing"

    if slug.startswith("event/"):
        slug = slug[len("event/") :]

    return f"https://vision.hack2skill.com/event/{slug}"


def _normalize_datetime(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_iso(value):
    parsed = _normalize_datetime(value)
    return parsed.date().isoformat() if parsed else None


def _status_from_dates(start_raw, end_raw):
    now = datetime.now(timezone.utc)
    start_dt = _normalize_datetime(start_raw)
    end_dt = _normalize_datetime(end_raw)

    if end_dt and end_dt < now:
        return "closed"
    if not start_dt or start_dt <= now:
        return "open"
    return "open"


def _devpost_period_to_dates(period_text):
    if not period_text:
        return None, None

    clean = " ".join(str(period_text).split())

    # Example: "Feb 26 - Apr 29, 2026"
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\s*-\s*([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})", clean)
    if match:
        sm, sd, em, ed, year = match.groups()
        try:
            start = datetime.strptime(f"{sm} {sd} {year}", "%b %d %Y").date().isoformat()
        except ValueError:
            start = None
        try:
            end = datetime.strptime(f"{em} {ed} {year}", "%b %d %Y").date().isoformat()
        except ValueError:
            end = None
        return start, end

    # Example: "April 1, 2026 - May 2, 2026"
    match = re.search(
        r"([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\s*-\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
        clean,
    )
    if match:
        start_raw, end_raw = match.groups()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                start = datetime.strptime(start_raw, fmt).date().isoformat()
                break
            except ValueError:
                start = None
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                end = datetime.strptime(end_raw, fmt).date().isoformat()
                break
            except ValueError:
                end = None
        return start, end

    return None, None


def _fetch_json(url, params=None):
    try:
        response = requests.get(
            url,
            params=params,
            timeout=25,
            headers={
                "User-Agent": "hackathonscraper/1.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc), "data": []}


def _scrape_hack2skill():
    payload = _fetch_json(HACK2SKILL_API_URL)
    items = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []

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
                "source": "hack2skill",
            }
        )

    return hackathons


def _scrape_devpost():
    payload = _fetch_json(
        DEVPOST_API_URL,
        params={
            "status[]": ["open", "upcoming"],
            "per_page": 50,
            "page": 1,
        },
    )
    items = payload.get("hackathons") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []

    hackathons = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not title:
            continue

        state = str(item.get("open_state") or "open").lower()
        start_iso, end_iso = _devpost_period_to_dates(item.get("submission_period_dates"))

        location_text = str((item.get("displayed_location") or {}).get("location") or "Online")
        location = "virtual" if "online" in location_text.lower() else "in_person"

        logo = item.get("thumbnail_url") or ""
        if logo.startswith("//"):
            logo = f"https:{logo}"

        hackathons.append(
            {
                "name": title,
                "location": location,
                "desc": (item.get("organization_name") or "Devpost") if isinstance(item, dict) else "Devpost",
                "date": {
                    "start": start_iso,
                    "end": end_iso,
                },
                "logo": logo,
                "status": "open" if state in {"open", "upcoming"} else "closed",
                "link": item.get("url") or "https://devpost.com/hackathons",
                "source": "devpost",
            }
        )

    return hackathons


def _scrape_unstop():
    payload = _fetch_json(
        UNSTOP_API_URL,
        params={
            "opportunity": "hackathons",
            "oppstatus": "open",
            "page": 1,
            "per_page": 50,
        },
    )

    data = payload.get("data") if isinstance(payload, dict) else {}
    items = data.get("data") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    hackathons = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not title:
            continue

        regn = item.get("regnRequirements") if isinstance(item.get("regnRequirements"), dict) else {}
        start_raw = regn.get("start_regn_dt")
        end_raw = regn.get("end_regn_dt") or item.get("end_date")

        region = str(item.get("region") or "online").lower()
        if "hybrid" in region:
            location = "hybrid"
        elif "offline" in region or "in_person" in region:
            location = "in_person"
        else:
            location = "virtual"

        link = item.get("seo_url")
        if not link:
            public_url = str(item.get("public_url") or "").lstrip("/")
            link = f"https://unstop.com/{public_url}" if public_url else "https://unstop.com/hackathons"

        org = item.get("organisation") if isinstance(item.get("organisation"), dict) else {}
        logo = item.get("logoUrl2") or org.get("logoUrl2") or org.get("logoUrl") or item.get("thumb") or ""

        status_text = str(item.get("status") or "open").lower()
        if status_text in {"open", "live", "active"}:
            status = "open"
        else:
            status = _status_from_dates(start_raw, end_raw)

        hackathons.append(
            {
                "name": title,
                "location": location,
                "desc": org.get("name") or "Unstop",
                "date": {
                    "start": _to_iso(start_raw),
                    "end": _to_iso(end_raw),
                },
                "logo": logo,
                "status": status,
                "link": link,
                "source": "unstop",
            }
        )

    return hackathons


def _dedupe(hackathons):
    deduped = []
    seen = set()
    for item in hackathons:
        key = str(item.get("link") or "").strip().lower()
        if not key:
            key = str(item.get("name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _is_not_expired(item):
    status = str(item.get("status") or "").strip().lower()
    if status == "closed":
        return False

    today = datetime.now(timezone.utc).date()
    end_raw = ((item.get("date") or {}).get("end") if isinstance(item.get("date"), dict) else None)
    if end_raw:
        try:
            end_date = datetime.fromisoformat(str(end_raw)).date()
            if end_date < today:
                return False
        except ValueError:
            # If date parsing fails, keep the item rather than dropping potentially valid data.
            pass

    return True


def scrape():
    combined = []
    combined.extend(_scrape_hack2skill())
    combined.extend(_scrape_devpost())
    combined.extend(_scrape_unstop())

    filtered = [item for item in _dedupe(combined) if _is_not_expired(item)]
    return json.dumps(filtered, sort_keys=True, indent=2)


def jsondump():
    with open("hackathons.JSON", "w", encoding="utf-8") as f:
        f.write(scrape())
