from __future__ import annotations

import logging
from typing import Any

from server.config import CACHE_DIR, SEC_HEADERS
from server.data.cache import JsonCache
from server.data.http import http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def _normalize_ticker(symbol: str) -> str:
    return (symbol or "").strip().upper()


async def ticker_map() -> dict[str, int]:
    async def factory() -> dict[str, int]:
        payload = await http.get_json(TICKERS_URL, headers=SEC_HEADERS)
        result: dict[str, int] = {}
        if isinstance(payload, dict):
            for item in payload.values():
                if not isinstance(item, dict):
                    continue
                ticker = str(item.get("ticker") or "").upper()
                cik = item.get("cik_str")
                if ticker and cik:
                    result[ticker] = int(cik)
        return result

    return await cache.get("sec:tickers:v1", 24 * 3600, factory)


async def cik_for(symbol: str) -> str | None:
    base = _normalize_ticker(symbol)
    mapping = await ticker_map()
    candidates = [base, base.replace(".", "-"), base.replace(".", ""), base.replace("_", "-")]
    for candidate in candidates:
        cik = mapping.get(candidate)
        if cik:
            return f"{cik:010d}"
    return None


def _doc_url(cik: str, accession: str, document: str | None) -> str:
    accession_clean = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}"
    if document:
        return f"{base}/{document}"
    return f"{base}/{accession}-index.htm"


INDEX_COLUMNS = (
    ("accessionNumber", "accession"),
    ("filingDate", "date"),
    ("reportDate", "report_date"),
    ("form", "form"),
    ("primaryDocument", "document"),
    ("primaryDocDescription", "description"),
    ("items", "items"),
    ("isXBRL", "is_xbrl"),
)
REPORT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
MATERIAL_FORMS = REPORT_FORMS | {
    "8-K", "8-K/A", "6-K", "6-K/A", "DEF 14A", "DEF 14A/A", "PRE 14A",
    "SC 13G", "SC 13G/A", "SC 13D", "SC 13D/A", "S-1", "S-1/A", "S-3", "S-3/A",
    "424B5", "425",
}
INDEX_RECENT_LIMIT = 80
INDEX_REPORT_LIMIT = 80
INDEX_MATERIAL_LIMIT = 60


async def _index(cik: str) -> dict[str, Any]:
    """One upstream fetch per CIK; overview and MD&A share the compact index."""

    async def factory() -> dict[str, Any]:
        payload = await http.get_json(SUBMISSIONS_URL.format(cik=cik), headers=SEC_HEADERS)
        recent = (((payload or {}).get("filings") or {}).get("recent") or {}) if isinstance(payload, dict) else {}
        columns = {source: recent.get(source) or [] for source, _ in INDEX_COLUMNS}
        count = len(columns["accessionNumber"])
        recent_rows: list[dict[str, Any]] = []
        report_rows: list[dict[str, Any]] = []
        material_rows: list[dict[str, Any]] = []
        for index in range(count):
            row = {
                target: (columns[source][index] if index < len(columns[source]) else None)
                for source, target in INDEX_COLUMNS
            }
            row["report_date"] = row.get("report_date") or None
            row["description"] = row.get("description") or ""
            row["items"] = row.get("items") or ""
            row["is_xbrl"] = bool(row.get("is_xbrl"))
            form = row.get("form")
            if len(recent_rows) < INDEX_RECENT_LIMIT:
                recent_rows.append(row)
            if form in REPORT_FORMS and len(report_rows) < INDEX_REPORT_LIMIT:
                report_rows.append(row)
            if form in MATERIAL_FORMS and len(material_rows) < INDEX_MATERIAL_LIMIT:
                material_rows.append(row)
            if (
                len(recent_rows) >= INDEX_RECENT_LIMIT
                and len(report_rows) >= INDEX_REPORT_LIMIT
                and len(material_rows) >= INDEX_MATERIAL_LIMIT
            ):
                break
        return {
            "company": (payload or {}).get("name") if isinstance(payload, dict) else None,
            "recent": recent_rows,
            "reports": report_rows,
            "material": material_rows,
        }

    return await cache.get(f"sec:index:v2:{cik}", 6 * 3600, factory)


def _filing_item(cik: str, row: dict[str, Any]) -> dict[str, Any]:
    accession = row.get("accession") or ""
    return {
        "accession": accession,
        "date": row.get("date"),
        "report_date": row.get("report_date"),
        "form": row.get("form"),
        "description": row.get("description") or "",
        "items": row.get("items") or "",
        "url": _doc_url(cik, accession, row.get("document")),
        "index_url": _doc_url(cik, accession, None),
        "is_xbrl": bool(row.get("is_xbrl")),
    }


async def filings(symbol: str, limit: int = 18, forms: set[str] | None = None) -> dict[str, Any]:
    cik = await cik_for(symbol)
    if not cik:
        return {"cik": None, "items": []}
    index = await _index(cik)
    if forms:
        pool = index["reports"] if forms.issubset(REPORT_FORMS) else index["recent"]
        selected = [row for row in pool if row.get("form") in forms][:limit]
    else:
        material = index.get("material") or []
        selected = material[:limit]
        if not any(row.get("form") in ANNUAL_FORMS for row in selected):
            annual_pool = material + (index.get("reports") or [])
            annual = next((row for row in annual_pool if row.get("form") in ANNUAL_FORMS), None)
            if annual:
                if len(selected) >= limit:
                    selected[-1] = annual
                else:
                    selected.append(annual)
        if len(selected) < limit:
            seen = {row.get("accession") for row in selected}
            for row in index["recent"]:
                if len(selected) >= limit:
                    break
                if row.get("accession") in seen:
                    continue
                selected.append(row)
                seen.add(row.get("accession"))
    items = [_filing_item(cik, row) for row in selected]
    items.sort(key=lambda item: item.get("date") or "", reverse=True)
    return {
        "cik": cik,
        "company": index.get("company"),
        "items": items,
        "source": "sec_edgar",
    }
