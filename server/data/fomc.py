from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from lxml import html as lxml_html

from server.config import BROWSER_UA, CACHE_DIR
from server.data.cache import JsonCache
from server.data.http import http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)
ET = ZoneInfo("America/New_York")
BASE = "https://www.federalreserve.gov"
CALENDAR_URL = f"{BASE}/monetarypolicy/fomccalendars.htm"
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml",
    "Referer": f"{BASE}/monetarypolicy/fomccalendars.htm",
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _href(value: str) -> str:
    return urljoin(BASE, value) if value else ""


def _link(row, pattern: str) -> str | None:
    for anchor in row.xpath(".//a[@href]"):
        href = str(anchor.get("href") or "")
        if re.search(pattern, href):
            return _href(href)
    return None


def _parse_calendar(document) -> list[dict[str, Any]]:
    meetings: list[dict[str, Any]] = []
    for panel in document.xpath('//div[contains(@class, "panel") and contains(@class, "panel-default")]'):
        heading = _text(" ".join(panel.xpath(".//h4//text()")))
        year_match = re.search(r"(20\d{2})\s+FOMC Meetings", heading)
        if not year_match:
            continue
        year = int(year_match.group(1))
        for row in panel.xpath('.//div[contains(@class, "fomc-meeting")]'):
            month_text = _text(" ".join(row.xpath('.//div[contains(@class, "fomc-meeting__month")]//text()')))
            date_text = _text(" ".join(row.xpath('.//div[contains(@class, "fomc-meeting__date")]//text()')))
            month = MONTHS.get(month_text.lower())
            days = [int(value) for value in re.findall(r"\d+", date_text)]
            if not month or not days:
                continue
            decision = date(year, month, days[-1])
            if not (2021 <= year <= 2100):
                continue
            statement_url = _link(row, r"/monetary\d{8}a\.htm$")
            implementation_url = _link(row, r"/monetary\d{8}a1\.htm$")
            minutes_url = _link(row, r"fomcminutes\d{8}\.htm$")
            projections_url = _link(row, r"fomcprojtabl\d{8}\.htm$")
            press_url = _link(row, r"pressconf\d{8}\.htm$")
            minutes_release = None
            release_match = re.search(r"Released\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", _text(row.text_content()))
            if release_match:
                try:
                    minutes_release = datetime.strptime(release_match.group(1), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass
            meetings.append(
                {
                    "date": decision.isoformat(),
                    "month": month_text,
                    "year": year,
                    "day_range": date_text.replace("*", "").replace("-", "–"),
                    "has_projections": "*" in date_text,
                    "statement_url": statement_url,
                    "implementation_note_url": implementation_url,
                    "minutes_url": minutes_url,
                    "minutes_released": minutes_release,
                    "sep_url": projections_url,
                    "press_conference_url": press_url,
                }
            )
    meetings.sort(key=lambda item: item["date"])
    return meetings


async def _calendar_document():
    text = await http.get_text(CALENDAR_URL, headers=HEADERS, timeout=18)
    return lxml_html.fromstring(text)


async def calendar() -> dict[str, Any]:
    """Fetch and parse the official FOMC calendar; cached for six hours."""

    async def factory() -> dict[str, Any]:
        document = await _calendar_document()
        meetings = _parse_calendar(document)
        if not meetings:
            raise ValueError("FOMC calendar structure unavailable")
        today = datetime.now(ET).date()
        past = [item for item in meetings if _date(item["date"]) and _date(item["date"]) < today]
        upcoming = [item for item in meetings if _date(item["date"]) and _date(item["date"]) >= today]
        return {
            "available": True,
            "source": "Federal Reserve Board",
            "source_url": CALENDAR_URL,
            "as_of": datetime.now(ET).isoformat(timespec="seconds"),
            "meetings": meetings,
            "past": past[-6:],
            "upcoming": upcoming[:6],
        }

    return await cache.get("fomc:calendar:v2", 6 * 3600, factory)


async def _statement_page(url: str) -> dict[str, Any]:
    async def factory() -> dict[str, Any]:
        text = await http.get_text(url, headers=HEADERS, timeout=18)
        document = lxml_html.fromstring(text)
        title = _text(" ".join(document.xpath('//div[@id="article"]//h3[contains(@class,"title")]//text()')))
        published = _text(" ".join(document.xpath('//div[@id="article"]//p[contains(@class,"article__time")]//text()')))
        paragraphs = []
        for node in document.xpath('//div[@id="article"]//p[not(ancestor::div[contains(@class,"heading")])]'):
            value = _text(node.text_content())
            if not value:
                continue
            lower = value.lower()
            if any(marker in lower for marker in (
                "for media inquiries", "implementation note", "board of governors",
                "[email", "email protected",
            )):
                continue
            paragraphs.append(value)
        intro = next((item for item in paragraphs if "approved the following statement" in item.lower()), "")
        content = [item for item in paragraphs if item != intro]
        decision = next((item for item in content if "target range for the federal funds rate" in item.lower()), "")
        dissent = next((item for item in content if item.lower().startswith("voting against")), "")
        vote_match = re.search(r"by a\s+([0-9]+(?:\s*[–-]\s*[0-9]+)?)\s+vote", intro, re.I)
        body = [item for item in content if item != dissent]
        excerpt = " ".join(body[:3])
        if len(excerpt) > 1100:
            excerpt = excerpt[:1100].rsplit(" ", 1)[0] + "…"
        return {
            "title": title or "FOMC statement",
            "published": published,
            "intro": intro,
            "decision": decision,
            "vote": vote_match.group(1).replace(" ", "") if vote_match else None,
            "dissent": dissent or None,
            "excerpt": excerpt,
        }

    return await cache.get(f"fomc:statement:v1:{url}", 12 * 3600, factory)


async def briefing() -> dict[str, Any]:
    """Assemble official FOMC schedule, latest statement and document links."""

    try:
        schedule = await calendar()
    except Exception as exc:
        logger.warning("FOMC calendar unavailable: %s", exc)
        return {
            "available": False,
            "source": "Federal Reserve Board",
            "source_url": CALENDAR_URL,
            "error": str(exc),
            "meetings": [],
            "upcoming": [],
            "latest_statement": None,
            "latest_minutes": None,
            "latest_sep": None,
        }

    today = datetime.now(ET).date()
    meetings = schedule.get("meetings") or []
    past = [item for item in meetings if _date(item["date"]) and _date(item["date"]) < today]
    upcoming = [item for item in meetings if _date(item["date"]) and _date(item["date"]) >= today]
    latest_with_statement = next(
        (item for item in reversed(past) if item.get("statement_url")), None
    )
    latest_minutes = next(
        (item for item in reversed(past) if item.get("minutes_url")), None
    )
    latest_sep = next(
        (item for item in reversed(past) if item.get("sep_url")), None
    )

    statement = None
    if latest_with_statement:
        try:
            parsed = await _statement_page(latest_with_statement["statement_url"])
            statement = {
                **parsed,
                "date": latest_with_statement["date"],
                "url": latest_with_statement["statement_url"],
                "implementation_note_url": latest_with_statement.get("implementation_note_url"),
                "minutes_url": latest_with_statement.get("minutes_url"),
                "minutes_released": latest_with_statement.get("minutes_released"),
                "sep_url": latest_with_statement.get("sep_url"),
            }
        except Exception as exc:
            logger.warning("FOMC statement unavailable: %s", exc)
            statement = {
                "date": latest_with_statement["date"],
                "title": "FOMC statement",
                "url": latest_with_statement["statement_url"],
                "excerpt": "官方声明原文暂时不可用，请通过源链接查看。",
                "implementation_note_url": latest_with_statement.get("implementation_note_url"),
                "minutes_url": latest_with_statement.get("minutes_url"),
                "minutes_released": latest_with_statement.get("minutes_released"),
                "sep_url": latest_with_statement.get("sep_url"),
            }

    next_meeting = upcoming[0] if upcoming else None
    if next_meeting:
        target = _date(next_meeting["date"])
        next_meeting = {**next_meeting, "days_until": (target - today).days if target else None}

    return {
        "available": True,
        "source": "Federal Reserve Board",
        "source_url": CALENDAR_URL,
        "as_of": datetime.now(ET).isoformat(timespec="seconds"),
        "next_meeting": next_meeting,
        "upcoming": [
            {
                **item,
                "days_until": (
                    (_date(item["date"]) - today).days
                    if _date(item["date"])
                    else None
                ),
            }
            for item in upcoming[:4]
        ],
        "recent": list(reversed(past[-6:])),
        "latest_statement": statement,
        "latest_minutes": (
            {
                "date": latest_minutes["date"],
                "url": latest_minutes.get("minutes_url"),
                "released": latest_minutes.get("minutes_released"),
            }
            if latest_minutes
            else None
        ),
        "latest_sep": (
            {
                "date": latest_sep["date"],
                "url": latest_sep.get("sep_url"),
            }
            if latest_sep
            else None
        ),
        "note": "会议日期、声明与纪要来自 Federal Reserve Board 官方页面；点阵图仅链接官方 SEP，不在本项目内推算。",
    }
