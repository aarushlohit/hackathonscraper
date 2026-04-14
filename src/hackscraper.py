#!/usr/bin/env python3
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests

HACK2SKILL_API_URL = (
    "https://vision.hack2skill.com/api/v1/innovator/public/event/public-list"
    "?page=1&records=50&search=&start=2024-01-01T00:00:00.000Z&end=2028-01-01T00:00:00.000Z"
)
DEVPOST_API_URL = "https://devpost.com/api/hackathons"
UNSTOP_API_URL = "https://unstop.com/api/public/opportunity/search-result"
DEVFOLIO_LISTING_URL = "https://devfolio.co/hackathons"
HACKEREARTH_LISTING_URL = "https://www.hackerearth.com/challenges/hackathon/"
DORAHACKS_LISTING_MIRROR_URL = "https://r.jina.ai/http://dorahacks.io/hackathon"
DORAHACKS_DETAIL_MIRROR_PREFIX = "https://r.jina.ai/http://dorahacks.io/hackathon/"
MLH_EVENTS_URL = "https://www.mlh.com/seasons/2026/events"


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
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
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


def _fetch_text(url, params=None):
    try:
        response = requests.get(
            url,
            params=params,
            timeout=15,
            headers={
                "User-Agent": "hackathonscraper/1.0",
                "Accept": "text/html,text/plain,*/*",
            },
        )
        response.raise_for_status()
        return response.text
    except Exception:
        return ""


def _safe_iso_from_yyyy_mm_dd(raw_date):
    if not raw_date:
        return None
    try:
        return datetime.strptime(str(raw_date), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _safe_iso_from_yyyy_slash_mm_slash_dd(raw_date):
    if not raw_date:
        return None
    try:
        return datetime.strptime(str(raw_date), "%Y/%m/%d").date().isoformat()
    except ValueError:
        return None


def _extract_title_from_html(html):
    if not html:
        return None
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _clean_event_url(raw_url):
    if not raw_url:
        return ""

    decoded = html.unescape(str(raw_url).strip())
    parsed = urlsplit(decoded)
    if not parsed.scheme or not parsed.netloc:
        return decoded
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _extract_devfolio_payload_from_html(html):
    if not html:
        return {}
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}

    queries = (
        ((data.get("props") or {}).get("pageProps") or {}).get("dehydratedState") or {}
    ).get("queries") or []
    if not queries:
        return {}

    state = (queries[0].get("state") or {}).get("data")
    return state if isinstance(state, dict) else {}


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


def _scrape_devfolio():
    html = _fetch_text(DEVFOLIO_LISTING_URL)
    payload = _extract_devfolio_payload_from_html(html)
    if not payload:
        return []

    sections = []
    for section_name in ("open_hackathons", "upcoming_hackathons", "featured_hackathons"):
        section_items = payload.get(section_name)
        if isinstance(section_items, list):
            sections.extend(section_items)

    hackathons = []
    for item in sections:
        if not isinstance(item, dict):
            continue

        title = item.get("name")
        slug = item.get("slug")
        if not title or not slug:
            continue

        start_raw = item.get("starts_at")
        end_raw = item.get("ends_at")
        settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}

        logo = (
            settings.get("featured_cover_img_v2")
            or settings.get("featured_cover_img")
            or ""
        )

        theme_names = []
        for theme_item in item.get("themes") or []:
            if not isinstance(theme_item, dict):
                continue
            theme = theme_item.get("theme") if isinstance(theme_item.get("theme"), dict) else {}
            name = theme.get("name")
            if name:
                theme_names.append(name)

        hackathons.append(
            {
                "name": title,
                "location": "virtual" if bool(item.get("is_online")) else "in_person",
                "desc": ", ".join(theme_names) if theme_names else "Devfolio",
                "date": {
                    "start": _to_iso(start_raw),
                    "end": _to_iso(end_raw),
                },
                "logo": logo,
                "status": _status_from_dates(start_raw, end_raw),
                "link": f"https://devfolio.co/hackathons/{slug}",
                "source": "devfolio",
            }
        )

    return hackathons


def _scrape_hackerearth():
    listing_html = _fetch_text(HACKEREARTH_LISTING_URL)
    if not listing_html:
        return []

    # HackerEarth page mixes live and previous items; keep only links before the
    # "PREVIOUS CHALLENGES" heading to avoid past hackathons.
    previous_marker = re.search(r"PREVIOUS\s+CHALLENGES", listing_html, re.IGNORECASE)
    live_section_html = listing_html[: previous_marker.start()] if previous_marker else listing_html

    raw_links = re.findall(r'https://www\.hackerearth\.com/challenges/hackathon/[^"\'\s<>]+', live_section_html)
    links = []
    for link in raw_links:
        cleaned = link.strip()
        if cleaned.endswith("/challenges/hackathon/"):
            continue
        if "update=" in cleaned:
            continue
        if cleaned not in links:
            links.append(cleaned)

    hackathons = []
    for link in links[:30]:
        base_name = re.sub(r"[-_/]+", " ", link.rstrip("/").split("/")[-1]).strip().title()
        detail_html = _fetch_text(link)
        if detail_html:
            title = _extract_title_from_html(detail_html)
            title = re.sub(r"\s*\|\s*HackerEarth.*$", "", title, flags=re.IGNORECASE) if title else base_name

            # Detail pages expose date tokens in ISO format; use min/max as best effort.
            iso_dates = sorted(set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", detail_html)))
            start_iso = _safe_iso_from_yyyy_mm_dd(iso_dates[0]) if iso_dates else None
            end_iso = _safe_iso_from_yyyy_mm_dd(iso_dates[-1]) if iso_dates else None

            image_match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', detail_html, re.IGNORECASE)
            logo = image_match.group(1).strip() if image_match else ""

            lower_html = detail_html.lower()
            location = "in_person" if any(token in lower_html for token in ["physical hackathon", "in-person", "onsite"]) else "virtual"
            status = _status_from_dates(start_iso, end_iso) if end_iso else "open"
        else:
            title = base_name
            start_iso = None
            end_iso = None
            logo = ""
            location = "virtual"
            status = "open"

        hackathons.append(
            {
                "name": title,
                "location": location,
                "desc": "HackerEarth",
                "date": {
                    "start": start_iso,
                    "end": end_iso,
                },
                "logo": logo,
                "status": status,
                "link": link,
                "source": "hackerearth",
            }
        )

    return hackathons


def _scrape_dorahacks():
    listing_text = _fetch_text(DORAHACKS_LISTING_MIRROR_URL)
    if not listing_text:
        return []

    slugs = []
    for slug in re.findall(r'https?://dorahacks\.io/hackathon/([a-zA-Z0-9-]+)', listing_text):
        if slug == "initiate":
            continue
        if slug not in slugs:
            slugs.append(slug)

    hackathons = []
    for slug in slugs[:25]:
        # Add a listing-level fallback record first; detail page will enrich it if available.
        item = {
            "name": re.sub(r"[-_]+", " ", slug).strip().title(),
            "location": "virtual",
            "desc": "DoraHacks",
            "date": {
                "start": None,
                "end": None,
            },
            "logo": "",
            "status": "open",
            "link": f"https://dorahacks.io/hackathon/{slug}",
            "source": "dorahacks",
        }

        detail_text = _fetch_text(f"{DORAHACKS_DETAIL_MIRROR_PREFIX}{slug}")
        if detail_text:
            title_match = re.search(r"Title:\s*(.*?)\s*\|\s*Hackathon\s*\|\s*DoraHacks", detail_text, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else None
            if title:
                item["name"] = title

            start_match = re.search(r"Submission\s+(\d{4}/\d{2}/\d{2})", detail_text, re.IGNORECASE)
            end_match = re.search(r"Deadline\s+(\d{4}/\d{2}/\d{2})", detail_text, re.IGNORECASE)
            start_iso = _safe_iso_from_yyyy_slash_mm_slash_dd(start_match.group(1)) if start_match else None
            end_iso = _safe_iso_from_yyyy_slash_mm_slash_dd(end_match.group(1)) if end_match else None
            item["date"] = {
                "start": start_iso,
                "end": end_iso,
            }

            if re.search(r"\bEnded\b", detail_text, re.IGNORECASE):
                item["status"] = "closed"
            elif end_iso:
                item["status"] = _status_from_dates(start_iso, end_iso)

            item["location"] = "virtual" if re.search(r"\bVirtual\b", detail_text, re.IGNORECASE) else "in_person"

            logo_match = re.search(r"(https://cdn\.dorahacks\.io/static/files/[^\s)]+)", detail_text)
            if logo_match:
                item["logo"] = logo_match.group(1).strip()

            prize_match = re.search(r"Prize pool\s+([^\n]+)", detail_text, re.IGNORECASE)
            if prize_match:
                item["desc"] = prize_match.group(1).strip()

        hackathons.append(item)

    return hackathons


def _scrape_mlh():
    listing_html = _fetch_text(MLH_EVENTS_URL)
    if not listing_html:
        return []

    upcoming_match = re.search(r"<h2[^>]*>\s*Upcoming\s+Events\s*</h2>", listing_html, re.IGNORECASE)
    past_match = re.search(r"<h2[^>]*>\s*Past\s+Events\s*</h2>", listing_html, re.IGNORECASE)

    start_idx = upcoming_match.start() if upcoming_match else 0
    end_idx = past_match.start() if past_match and past_match.start() > start_idx else len(listing_html)
    upcoming_html = listing_html[start_idx:end_idx]

    cards = re.findall(
        r'<a[^>]+itemType="https://schema\.org/Event"[^>]*>.*?</a>',
        upcoming_html,
        re.IGNORECASE | re.DOTALL,
    )

    hackathons = []
    for card in cards:
        href_match = re.search(r'<a[^>]+href="([^"]+)"', card, re.IGNORECASE)
        meta_url_match = re.search(r'<meta[^>]+itemProp="url"[^>]+content="([^"]+)"', card, re.IGNORECASE)
        start_match = re.search(r'<meta[^>]+itemProp="startDate"[^>]+content="([^"]+)"', card, re.IGNORECASE)
        end_match = re.search(r'<meta[^>]+itemProp="endDate"[^>]+content="([^"]+)"', card, re.IGNORECASE)
        attendance_match = re.search(
            r'<meta[^>]+itemProp="eventAttendanceMode"[^>]+content="([^"]+)"',
            card,
            re.IGNORECASE,
        )

        title_match = re.search(r"<h4[^>]*>(.*?)</h4>", card, re.IGNORECASE | re.DOTALL)
        title = ""
        if title_match:
            title = re.sub(r"<[^>]+>", " ", title_match.group(1))
            title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        if not title:
            continue

        logo_match = re.search(r'<img[^>]+src="([^"]+)"', card, re.IGNORECASE)
        logo = html.unescape(logo_match.group(1)).strip() if logo_match else ""

        start_raw = start_match.group(1).strip() if start_match else None
        end_raw = end_match.group(1).strip() if end_match else None
        attendance_mode = attendance_match.group(1).strip().lower() if attendance_match else ""

        link = _clean_event_url(meta_url_match.group(1) if meta_url_match else (href_match.group(1) if href_match else ""))

        hackathons.append(
            {
                "name": title,
                "location": "virtual" if "onlineeventattendancemode" in attendance_mode else "in_person",
                "desc": "MLH",
                "date": {
                    "start": _to_iso(start_raw),
                    "end": _to_iso(end_raw),
                },
                "logo": logo,
                "status": _status_from_dates(start_raw, end_raw),
                "link": link or MLH_EVENTS_URL,
                "source": "mlh",
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
    def _safe_collect(source_callable):
        try:
            items = source_callable()
            return items if isinstance(items, list) else []
        except Exception:
            return []

    combined = []
    combined.extend(_safe_collect(_scrape_hack2skill))
    combined.extend(_safe_collect(_scrape_devpost))
    combined.extend(_safe_collect(_scrape_unstop))
    combined.extend(_safe_collect(_scrape_devfolio))
    combined.extend(_safe_collect(_scrape_hackerearth))
    combined.extend(_safe_collect(_scrape_dorahacks))
    combined.extend(_safe_collect(_scrape_mlh))

    filtered = [item for item in _dedupe(combined) if _is_not_expired(item)]
    return json.dumps(filtered, sort_keys=True, indent=2)


def jsondump():
    with open("hackathons.JSON", "w", encoding="utf-8") as f:
        f.write(scrape())
