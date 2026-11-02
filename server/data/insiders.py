"""EDGAR Form 4 内部人交易聚合：净买卖、集群买入、身份结构与成本对照。

只读公开申报：submissions JSON 取索引，再逐个抓取原始 XML 附表。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

from server.config import CACHE_DIR, SEC_HEADERS
from server.data import sec
from server.data.cache import JsonCache
from server.data.http import UpstreamError, http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
XSL_PREFIX = re.compile(r"^[^/]*xsl[^/]*/", re.IGNORECASE)
LOCAL_NAME = re.compile(r"^\{[^}]+\}")
OPEN_BUY = {"P"}
OPEN_SELL = {"S"}
NOISE_CODES = {"F", "G", "A", "C", "D", "X", "Z"}


def _tag(element: ET.Element) -> str:
    return LOCAL_NAME.sub("", element.tag)


def _find(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if _tag(child) == name:
            return child
    return None


def _leaf(element: ET.Element | None) -> str:
    """Form 4 的数值都藏在 <tag>/<child>value</child> 里，取第一个有文本的后代。"""
    if element is None:
        return ""
    if (element.text or "").strip():
        return element.text.strip()
    for child in element:
        value = _leaf(child)
        if value:
            return value
    return ""


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _tag(child) == name]


def _num(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _flag(value: str) -> bool:
    # EDGAR 的 Form 4 同时存在 "1"/"0" 与 "true"/"false" 两种布尔写法
    return str(value).strip().lower() in {"1", "true", "yes"}


def _desc(element: ET.Element, name: str) -> ET.Element | None:
    for node in element.iter():
        if _tag(node) == name:
            return node
    return None


def _field(element: ET.Element, *names: str) -> str:
    for name in names:
        value = _leaf(_desc(element, name))
        if value:
            return value
    return ""


def _walk_transactions(root: ET.Element) -> list[dict[str, Any]]:
    """遍历非衍生与衍生两张表，产出统一的交易流水。"""
    owner = _find(root, "reportingOwner") or root
    name = _field(owner, "rptOwnerName", "reportingOwnerName")
    titles = [_leaf(_desc(owner, "officerTitle"))]
    title_array = _desc(owner, "reportingOwnerTitleArray")
    if title_array is not None:
        titles += [_leaf(node) for node in _children(title_array, "reportingOwnerTitle")]
    titles = [item for item in titles if item]
    flags = (
        ("董事", _flag(_field(owner, "isDirector", "directors"))),
        ("高管", _flag(_field(owner, "isOfficer", "officers"))),
        ("10% 股东", _flag(_field(owner, "isTenPercentOwner", "tenPercentOwner"))),
    )
    role = "/".join(label for label, active in flags if active) or "其他内部人"
    if _flag(_field(root, "aff10b5One")):
        role = f"{role}·10b5-1"

    rows: list[dict[str, Any]] = []
    for block in root.iter():
        if _tag(block) not in {"nonDerivativeTransaction", "derivativeTransaction"}:
            continue
        date_value = _field(block, "transactionDate")
        shares = _num(_field(block, "transactionShares"))
        if not date_value or not shares:
            continue
        price = _num(_field(block, "transactionPricePerShare"))
        rows.append(
            {
                "date": date_value,
                "security": _field(block, "securityTitle"),
                "code": _field(block, "transactionCode", "acquireDispositionCode"),
                "adc": _field(block, "transactionAcquiredDisposedCode"),
                "shares": abs(shares),
                "price": price,
                "value": abs(shares) * (price or 0),
                "after": _num(_field(block, "sharesOwnedFollowingTransaction")),
                "direct": _field(block, "directOrIndirectOwnership") != "I",
                "name": name,
                "role": role,
                "title": titles[0] if titles else "",
            }
        )
    return rows


async def _form4_index(cik: str, months: int) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=months * 31)

    async def factory() -> list[dict[str, Any]]:
        payload = await http.get_json(
            SUBMISSIONS_URL.format(cik=cik), headers=SEC_HEADERS, retries=1, timeout=45
        )
        recent = (((payload or {}).get("filings") or {}).get("recent") or {}) if isinstance(payload, dict) else {}
        forms = recent.get("form") or []
        rows = []
        for index, form in enumerate(forms):
            if form not in {"4", "4/A"}:
                continue
            filing_date = str((recent.get("filingDate") or [""] * len(forms))[index] or "")
            try:
                parsed = datetime.strptime(filing_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if parsed < cutoff:
                continue
            document = str((recent.get("primaryDocument") or [""] * len(forms))[index] or "")
            if not document:
                continue
            rows.append(
                {
                    "accession": str((recent.get("accessionNumber") or [""] * len(forms))[index] or ""),
                    "filing_date": filing_date,
                    "report_date": str((recent.get("reportDate") or [""] * len(forms))[index] or ""),
                    "document": XSL_PREFIX.sub("", document),
                }
            )
        return rows[:120]

    return await cache.get(f"sec:form4:v1:{cik}:{months}", 12 * 3600, factory)


def _clusters(buys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """30 天滚动窗口内 ≥3 位不同内部人的公开市场买入视为集群买入。"""
    if len(buys) < 3:
        return []
    ordered = sorted(buys, key=lambda item: item["date"])
    best: dict[str, Any] | None = None
    for index, anchor in enumerate(ordered):
        try:
            start = datetime.strptime(anchor["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        window = [
            item
            for item in ordered[index:]
            if (datetime.strptime(item["date"], "%Y-%m-%d").date() - start).days <= 30
        ]
        people = {item["name"] for item in window}
        if len(people) < 3:
            continue
        candidate = {
            "start": anchor["date"],
            "end": max(item["date"] for item in window),
            "insiders": len(people),
            "trades": len(window),
            "shares": round(sum(item["shares"] for item in window)),
            "value": round(sum(item["value"] for item in window)),
        }
        if best is None or candidate["insiders"] > best["insiders"]:
            best = candidate
    return [best] if best else []


async def insider_activity(symbol: str, *, months: int = 12, price: float | None = None) -> dict[str, Any]:
    cik = await sec.cik_for(symbol)
    if not cik:
        raise UpstreamError("SEC CIK unavailable")
    index = await _form4_index(cik, months)
    if not index:
        return {"cik": cik, "filings": 0, "transactions": [], "summary": None}

    semaphore = asyncio.Semaphore(4)

    async def fetch(item: dict[str, Any]) -> list[dict[str, Any]]:
        url = ARCHIVE_URL.format(
            cik=int(cik), accession=item["accession"].replace("-", ""), document=item["document"]
        )
        async with semaphore:
            try:
                raw = await http.get_bytes(url, headers=SEC_HEADERS, retries=1, timeout=30)
                root = ET.fromstring(raw.decode("utf-8", errors="replace"))
            except Exception as exc:
                logger.debug("form4 parse failed for %s: %s", url, exc)
                return []
        rows = _walk_transactions(root)
        for row in rows:
            row["filing_date"] = item["filing_date"]
            if not row["date"]:
                row["date"] = item["report_date"]
        return rows

    chunks = await asyncio.gather(*(fetch(item) for item in index))
    transactions = [row for chunk in chunks for row in chunk if row.get("date")]
    transactions.sort(key=lambda item: item["date"], reverse=True)

    open_buys = [item for item in transactions if item["code"] in OPEN_BUY and item["adc"] == "A" and item["direct"]]
    open_sells = [item for item in transactions if item["code"] in OPEN_SELL and item["adc"] == "D" and item["direct"]]
    buy_ids = {id(item) for item in open_buys}
    sell_ids = {id(item) for item in open_sells}
    buy_value = sum(item["value"] for item in open_buys)
    sell_value = sum(item["value"] for item in open_sells)
    buy_shares = sum(item["shares"] for item in open_buys)
    avg_cost = (buy_value / buy_shares) if buy_shares else None
    people = {item["name"] for item in transactions if item["name"]}
    buyers = {item["name"] for item in open_buys}
    sellers = {item["name"] for item in open_sells}
    by_person: dict[str, dict[str, Any]] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "trades": 0, "role": "", "title": ""})
    for item in transactions:
        key = item["name"] or "未具名"
        bucket = by_person[key]
        bucket["trades"] += 1
        bucket["role"] = bucket["role"] or item["role"]
        bucket["title"] = bucket["title"] or item["title"]
        if id(item) in buy_ids:
            bucket["buy"] += item["value"]
        elif id(item) in sell_ids:
            bucket["sell"] += item["value"]
    ranked = sorted(
        (
            {
                "name": key,
                "role": value["role"],
                "title": value["title"],
                "buy_value": round(value["buy"]),
                "sell_value": round(value["sell"]),
                "net_value": round(value["buy"] - value["sell"]),
                "trades": value["trades"],
            }
            for key, value in by_person.items()
        ),
        key=lambda item: abs(item["net_value"]),
        reverse=True,
    )
    months_seen = {item["date"][:7] for item in open_buys}
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
    for item in transactions:
        key = item["date"][:7]
        if id(item) in buy_ids:
            monthly[key]["buy"] += item["value"]
        elif id(item) in sell_ids:
            monthly[key]["sell"] += item["value"]
    timeline = [
        {
            "month": key,
            "buy": round(value["buy"]),
            "sell": round(-value["sell"]),
        }
        for key, value in sorted(monthly.items())
    ][-18:]
    summary = {
        "window_months": months,
        "insiders": len(people),
        "buy_insiders": len(buyers),
        "sell_insiders": len(sellers),
        "buy_trades": len(open_buys),
        "sell_trades": len(open_sells),
        "grant_trades": sum(1 for item in transactions if item["code"] in {"A", "M", "X"}),
        "buy_value": round(buy_value),
        "sell_value": round(sell_value),
        "net_value": round(buy_value - sell_value),
        "avg_buy_price": round(avg_cost, 2) if avg_cost else None,
        "vs_price_pct": round((price - avg_cost) / avg_cost * 100, 1)
        if price and avg_cost
        else None,
        "buy_months": len(months_seen),
        "officer_buys": sum(1 for item in open_buys if "高管" in item["role"]),
        "director_buys": sum(1 for item in open_buys if "董事" in item["role"]),
        "clusters": _clusters(open_buys),
        "timeline": timeline,
    }
    return {
        "cik": cik,
        "filings": len(index),
        "parsed": len(transactions),
        "summary": summary,
        "people": ranked[:12],
        "transactions": [
            {
                "date": item["date"],
                "name": item["name"],
                "role": item["role"],
                "title": item["title"],
                "code": item["code"],
                "adc": item["adc"],
                "shares": round(item["shares"]),
                "price": item["price"],
                "value": round(item["value"]),
                "after": round(item["after"]) if item["after"] is not None else None,
                "direct": item["direct"],
                "noise": item["code"] in NOISE_CODES,
            }
            for item in transactions[:60]
        ],
        "source": "sec_edgar_form4",
    }
