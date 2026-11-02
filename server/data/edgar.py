from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from bisect import bisect_left
from copy import deepcopy
from collections import Counter
from datetime import date, datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from lxml import etree as lxml_etree
from lxml import html as lxml_html

from server.config import CACHE_DIR, SEC_HEADERS
from server.data import sec
from server.data.cache import JsonCache
from server.data.http import http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)
ET = ZoneInfo("America/New_York")

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
REPORT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
SEC_MIN_INTERVAL = 0.12

_throttle_lock = asyncio.Lock()
_next_slot = 0.0


async def _throttle_sec() -> None:
    global _next_slot
    async with _throttle_lock:
        now = time.monotonic()
        if _next_slot > now:
            await asyncio.sleep(_next_slot - now)
        _next_slot = time.monotonic() + SEC_MIN_INTERVAL


async def _sec_json(url: str) -> Any:
    await _throttle_sec()
    return await http.get_json(url, headers=SEC_HEADERS, retries=1, timeout=45)


async def _sec_bytes(url: str) -> bytes:
    await _throttle_sec()
    return await http.get_bytes(url, headers=SEC_HEADERS, retries=1, timeout=45)


DURATION_ITEMS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_expenses": ("OperatingExpenses", "CostsAndExpenses"),
    "rnd": ("ResearchAndDevelopmentExpense",),
    "sga": (
        "SellingGeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "GeneralAndAdministrativeExpense",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "tax": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"),
    "shares_diluted": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    "ocf": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireRealEstate",
    ),
    "dividends_paid": ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
    "depreciation": ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet"),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating"),
}

INSTANT_ITEMS: dict[str, tuple[str, ...]] = {
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "current_assets": ("AssetsCurrent",),
    "total_assets": ("Assets",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_liabilities": ("Liabilities",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
    "goodwill": ("Goodwill",),
    "inventory": ("InventoryNet",),
    "receivables": ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
    "payables": (
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
        "AccountsPayableTradeCurrent",
    ),
    "ppe": ("PropertyPlantAndEquipmentNet",),
    "short_term_debt": ("LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper"),
    "shares_outstanding": ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"),
}

ITEM_UNITS = {
    "eps_diluted": "USD/shares",
    "shares_diluted": "shares",
    "shares_outstanding": "shares",
}
TAG_UNITS: dict[str, str] = {}
for _item, _tags in DURATION_ITEMS.items():
    for _tag in _tags:
        TAG_UNITS[_tag] = ITEM_UNITS.get(_item, "USD")
for _item, _tags in INSTANT_ITEMS.items():
    for _tag in _tags:
        TAG_UNITS[_tag] = ITEM_UNITS.get(_item, "USD")


def _span_days(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _compact_facts(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"entity": None, "tags": {}}
    gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    tags: dict[str, list[list[Any]]] = {}
    for tag, unit in TAG_UNITS.items():
        node = gaap.get(tag)
        if not isinstance(node, dict):
            continue
        values = (node.get("units") or {}).get(unit)
        if not isinstance(values, list):
            continue
        rows: list[list[Any]] = []
        for entry in values:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("form") or "") not in REPORT_FORMS:
                continue
            end = str(entry.get("end") or "")
            value = entry.get("val")
            if not end or not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            rows.append([str(entry.get("start") or ""), end, float(value), str(entry.get("filed") or "")])
        if rows:
            tags[tag] = rows
    return {"entity": payload.get("entityName"), "tags": tags}


async def _companyfacts(cik: str) -> dict[str, Any]:
    key = f"sec:facts:v3:{cik}"

    async def factory() -> dict[str, Any]:
        payload = await _sec_json(COMPANYFACTS_URL.format(cik=cik))
        return _compact_facts(payload)

    return await cache.get(key, 12 * 3600, factory)


def _series(tags: dict[str, list[list[Any]]], candidates: tuple[str, ...], *, min_span: int = 0, max_span: int = 0) -> dict[str, float]:
    best: dict[str, tuple[tuple[str, int], float]] = {}
    for index, tag in enumerate(candidates):
        for start, end, value, filed in tags.get(tag, []):
            if min_span:
                if not start:
                    continue
                span = _span_days(start, end)
                if span is None or span < min_span or span > max_span:
                    continue
            elif start:
                continue
            priority = (filed, -index)
            previous = best.get(end)
            if previous is None or priority > previous[0]:
                best[end] = (priority, value)
    return {end: value for end, (_, value) in best.items()}


def _nearest(series: dict[str, float], keys: list[str], target: str, tolerance: int) -> float | None:
    if not keys:
        return None
    position = bisect_left(keys, target)
    best_value: float | None = None
    best_diff = tolerance + 1
    for index in (position - 1, position):
        if 0 <= index < len(keys):
            key = keys[index]
            try:
                diff = abs((date.fromisoformat(key) - date.fromisoformat(target)).days)
            except ValueError:
                continue
            if diff < best_diff:
                best_diff = diff
                best_value = series.get(key)
    return best_value


def _build_rows(facts: dict[str, Any], *, quarterly: bool) -> list[dict[str, Any]]:
    tags = facts.get("tags") or {}
    duration: dict[str, dict[str, float]] = {}
    for item, candidates in DURATION_ITEMS.items():
        duration[item] = _series(
            tags,
            candidates,
            min_span=55 if quarterly else 300,
            max_span=125 if quarterly else 400,
        )
    instant: dict[str, dict[str, float]] = {}
    for item, candidates in INSTANT_ITEMS.items():
        instant[item] = _series(tags, candidates)

    ends: set[str] = set()
    for item in ("revenue", "net_income", "ocf", "operating_income", "eps_diluted", "capex"):
        ends.update(duration[item])
    periods = sorted(ends)[-(8 if quarterly else 6):]
    duration_keys = {item: sorted(values) for item, values in duration.items()}
    instant_keys = {item: sorted(values) for item, values in instant.items()}

    rows: list[dict[str, Any]] = []
    for end in periods:
        row: dict[str, Any] = {"date": end}
        for item in DURATION_ITEMS:
            row[item] = _nearest(duration[item], duration_keys[item], end, 7)
        for item in INSTANT_ITEMS:
            row[item] = _nearest(instant[item], instant_keys[item], end, 15)

        if row.get("gross_profit") is None and row.get("revenue") is not None and row.get("cost_of_revenue") is not None:
            row["gross_profit"] = row["revenue"] - row["cost_of_revenue"]
        if row.get("cost_of_revenue") is None and row.get("revenue") is not None and row.get("gross_profit") is not None:
            row["cost_of_revenue"] = row["revenue"] - row["gross_profit"]
        if (
            row.get("operating_income") is None
            and row.get("gross_profit") is not None
            and row.get("operating_expenses") is not None
        ):
            row["operating_income"] = row["gross_profit"] - row["operating_expenses"]
        if row.get("ocf") is not None and row.get("capex") is not None:
            row["fcf"] = row["ocf"] - abs(row["capex"])
        else:
            row["fcf"] = None

        for item, value in row.items():
            if item != "date" and isinstance(value, float):
                row[item] = round(value, 2)
        if any(row.get(item) is not None for item in ("revenue", "net_income", "ocf", "eps_diluted")):
            rows.append(row)
    return rows


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 2)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 2)


def _annual_ratios(rows: list[dict[str, Any]], *, days: int = 365) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        previous = rows[index - 1] if index else None

        def avg(item: str) -> float | None:
            current_value = row.get(item)
            previous_value = previous.get(item) if previous else None
            if current_value is None:
                return None
            if previous_value is None:
                return current_value
            return (current_value + previous_value) / 2

        revenue = row.get("revenue")
        net_income = row.get("net_income")
        ocf = row.get("ocf")
        cost = row.get("cost_of_revenue")
        assets = avg("total_assets")
        equity = avg("equity")
        pretax = row.get("pretax_income")
        tax_rate = (
            row["tax"] / pretax
            if pretax is not None and pretax > 0 and row.get("tax") is not None
            else None
        )
        tax_rate = max(0.0, min(0.6, tax_rate)) if tax_rate is not None else None
        nopat = (
            row["operating_income"] * (1 - (tax_rate if tax_rate is not None else 0.21))
            if row.get("operating_income") is not None
            else None
        )
        current_liabilities_avg = avg("current_liabilities")
        invested = (
            assets - current_liabilities_avg
            if assets is not None and current_liabilities_avg is not None
            else None
        )
        dso = row["receivables"] / revenue * days if revenue and row.get("receivables") is not None and revenue > 0 else None
        dio = row["inventory"] / cost * days if cost and row.get("inventory") is not None and cost > 0 else None
        dpo = row["payables"] / cost * days if cost and row.get("payables") is not None and cost > 0 else None
        ccc = dso + dio - dpo if dso is not None and dio is not None and dpo is not None else None
        returned = None
        if row.get("fcf") is not None and row["fcf"] > 0:
            returned = abs(row.get("dividends_paid") or 0) + abs(row.get("buybacks") or 0)
        growth = (
            (revenue - previous["revenue"]) / previous["revenue"] * 100
            if revenue is not None and previous and previous.get("revenue")
            else None
        )
        fcf_margin = _pct(row.get("fcf"), revenue)
        ratios = {
            "date": row["date"],
            "gross_margin": _pct(row.get("gross_profit"), revenue),
            "operating_margin": _pct(row.get("operating_income"), revenue),
            "net_margin": _pct(net_income, revenue),
            "fcf_margin": fcf_margin,
            "roe": _pct(net_income, equity),
            "roa": _pct(net_income, assets),
            "roic": _pct(nopat, invested) if days == 365 and invested is not None and invested > 0 else None,
            "current_ratio": _ratio(row.get("current_assets"), row.get("current_liabilities")),
            "cash_ratio": _ratio(row.get("cash"), row.get("current_liabilities")),
            "debt_to_equity": _ratio(row.get("total_liabilities"), row.get("equity")),
            "debt_to_assets": _ratio(row.get("long_term_debt") or row.get("total_liabilities"), row.get("total_assets")),
            "asset_turnover": _ratio(revenue, assets),
            "ocf_to_ni": _ratio(ocf, net_income) if net_income is not None and net_income > 0 else None,
            "accrual_ratio": _pct((net_income - ocf) if net_income is not None and ocf is not None else None, assets),
            "rd_intensity": _pct(row.get("rnd"), revenue),
            "sga_ratio": _pct(row.get("sga"), revenue),
            "capex_intensity": _pct(abs(row["capex"]) if row.get("capex") is not None else None, revenue),
            "effective_tax_rate": _pct(row.get("tax"), pretax) if pretax is not None and pretax > 0 else None,
            "interest_coverage": _ratio(row.get("operating_income"), row.get("interest_expense")),
            "dso": round(dso, 1) if dso is not None else None,
            "dio": round(dio, 1) if dio is not None else None,
            "dpo": round(dpo, 1) if dpo is not None else None,
            "ccc": round(ccc, 1) if ccc is not None else None,
            "fcf_conversion": _pct(row.get("fcf"), ocf) if ocf is not None and ocf > 0 else None,
            "shareholder_return": _pct(returned, row.get("fcf")) if returned is not None else None,
            "rule_of_40": round(growth + fcf_margin, 1) if growth is not None and fcf_margin is not None else None,
            "revenue_yoy": _pct(
                (revenue - previous["revenue"]) if revenue is not None and previous and previous.get("revenue") else None,
                previous.get("revenue") if previous else None,
            ),
            "eps_yoy": _pct(
                (row["eps_diluted"] - previous["eps_diluted"])
                if row.get("eps_diluted") is not None and previous and previous.get("eps_diluted")
                else None,
                previous.get("eps_diluted") if previous else None,
            ),
        }
        result.append(ratios)
    return result


FINANCIAL_HINTS = ("银行", "保险", "金融", "证券", "券商", "资本市场", "多元金融")


def _trend(rows: list[dict[str, Any]], ratios: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    window = min(len(rows), 5)
    rows = rows[-window:]
    years = len(rows) - 1

    def cagr(start: float | None, end: float | None) -> float | None:
        if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
            return None
        return round(((end / start) ** (1 / years) - 1) * 100, 2)

    def span(item: str, absolute: bool = False) -> float | None:
        first, last = rows[0].get(item), rows[-1].get(item)
        if first is None or last is None:
            return None
        if absolute:
            return abs(last) - abs(first)
        return last - first

    fcf_positive = sum(1 for row in rows if (row.get("fcf") or 0) > 0)
    latest_ratio = ratios[-1] if ratios else {}
    margin_start = ratios[-(window)] if len(ratios) >= window else (ratios[0] if ratios else {})

    def delta(key: str) -> float | None:
        start, end = margin_start.get(key), latest_ratio.get(key)
        if start is None or end is None:
            return None
        return round(end - start, 2)

    return {
        "years": years,
        "window": len(rows),
        "revenue_cagr": cagr(rows[0].get("revenue"), rows[-1].get("revenue")),
        "eps_cagr": cagr(rows[0].get("eps_diluted"), rows[-1].get("eps_diluted")),
        "fcf_cagr": cagr(rows[0].get("fcf"), rows[-1].get("fcf")),
        "ocf_cagr": cagr(rows[0].get("ocf"), rows[-1].get("ocf")),
        "revenue_change": span("revenue"),
        "fcf_change": span("fcf"),
        "gross_margin_change": delta("gross_margin"),
        "operating_margin_change": delta("operating_margin"),
        "roic_change": delta("roic"),
        "fcf_positive_years": fcf_positive,
    }


def _capital_allocation(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def bucket(row: dict[str, Any]) -> dict[str, Any]:
        dividends = abs(row.get("dividends_paid") or 0)
        buybacks = abs(row.get("buybacks") or 0)
        capex = abs(row.get("capex") or 0)
        fcf = row.get("fcf")
        return {
            "date": row.get("date"),
            "fcf": fcf,
            "dividends": dividends,
            "buybacks": buybacks,
            "capex": capex,
            "returned": dividends + buybacks,
            "retained": (fcf - dividends - buybacks) if fcf is not None else None,
            "payout_of_fcf": _pct(dividends + buybacks, fcf) if fcf is not None and fcf > 0 else None,
            "capex_of_ocf": _pct(capex, row.get("ocf")) if row.get("ocf") and row["ocf"] > 0 else None,
        }

    latest = bucket(rows[-1])
    window = rows[-3:]
    totals = {
        "years": len(window),
        "fcf": sum((row.get("fcf") or 0) for row in window) if any(row.get("fcf") is not None for row in window) else None,
        "dividends": sum(abs(row.get("dividends_paid") or 0) for row in window),
        "buybacks": sum(abs(row.get("buybacks") or 0) for row in window),
        "capex": sum(abs(row.get("capex") or 0) for row in window),
    }
    totals["returned"] = totals["dividends"] + totals["buybacks"]
    totals["payout_of_fcf"] = _pct(totals["returned"], totals["fcf"]) if totals["fcf"] and totals["fcf"] > 0 else None
    return {
        "latest": latest,
        "three_year": totals,
        "note": "股东回报 = 现金分红 + 股票回购；留存现金 = 自由现金流 - 股东回报。",
    }


def _statement_insights(
    rows: list[dict[str, Any]],
    ratios: list[dict[str, Any]],
    *,
    is_financial: bool = False,
    trend: dict[str, Any] | None = None,
    allocation: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if not rows or not ratios:
        return []
    row = rows[-1]
    ratio = ratios[-1]
    previous = ratios[-2] if len(ratios) > 1 else None
    insights: list[dict[str, str]] = []

    fcf = row.get("fcf")
    net_income = row.get("net_income")
    if not is_financial and fcf is not None and net_income is not None and net_income > 0:
        conversion = fcf / net_income
        if conversion >= 1:
            insights.append(
                {
                    "tone": "positive",
                    "text": f"自由现金流为净利润的 {conversion:.2f} 倍，利润的现金含量充足。",
                }
            )
        elif conversion < 0.5:
            insights.append(
                {
                    "tone": "caution",
                    "text": f"自由现金流仅覆盖净利润的 {conversion:.0%}，资本开支或营运资金占用偏高。",
                }
            )

    growth = ratio.get("revenue_yoy")
    margin = ratio.get("net_margin")
    margin_prev = previous.get("net_margin") if previous else None
    if growth is not None and margin is not None and margin_prev is not None:
        margin_delta = margin - margin_prev
        if growth > 5 and margin_delta < -1:
            insights.append(
                {
                    "tone": "caution",
                    "text": f"营收同比 {growth:+.1f}%，但净利率下降 {abs(margin_delta):.1f}pct，呈增收不增利特征。",
                }
            )
        elif growth < 0 and margin_delta > 1:
            insights.append(
                {
                    "tone": "positive",
                    "text": f"营收同比 {growth:+.1f}%，净利率反升 {margin_delta:.1f}pct，成本控制对冲了需求压力。",
                }
            )
        elif growth > 5 and margin_delta > 1:
            insights.append(
                {
                    "tone": "positive",
                    "text": f"营收同比 {growth:+.1f}%，净利率提升 {margin_delta:.1f}pct，规模效应与定价能力同步兑现。",
                }
            )

    roe = ratio.get("roe")
    if roe is not None:
        if roe >= 20:
            insights.append({"tone": "positive", "text": f"ROE 达 {roe:.1f}%，股东资本回报处于高位。"})
        elif roe < 0:
            insights.append({"tone": "caution", "text": f"ROE 为 {roe:.1f}%，账面资本正在被侵蚀。"})
        equity = row.get("equity")
        revenue = row.get("revenue")
        if roe >= 100 and equity is not None and revenue and equity < revenue * 0.2:
            insights.append(
                {
                    "tone": "neutral",
                    "text": f"账面权益仅相当于营收的 {equity / revenue:.0%}，ROE 被大额回购与低账面资本放大，建议结合 ROIC 解读。",
                }
            )
        roa = ratio.get("roa")
        if is_financial and roa is not None and roe < 20:
            insights.append(
                {
                    "tone": "positive" if roe >= 12 else "neutral" if roe >= 8 else "caution",
                    "text": f"ROE {roe:.1f}%、ROA {roa:.2f}%：金融企业依靠杠杆放大股东回报，需结合资产质量与资本充足率判断可持续性。",
                }
            )

    shares_now = row.get("shares_diluted")
    shares_prev = rows[-2].get("shares_diluted") if len(rows) > 1 else None
    if shares_now is not None and shares_prev is not None and shares_prev > 0:
        change = shares_now / shares_prev - 1
        if change > 0.02:
            insights.append(
                {
                    "tone": "caution",
                    "text": f"稀释股本同比增加 {change:.1%}，每股价值存在摊薄压力。",
                }
            )
        elif change < -0.02:
            insights.append(
                {
                    "tone": "positive",
                    "text": f"稀释股本同比减少 {abs(change):.1%}，回购对每股指标形成支撑。",
                }
            )

    roic = ratio.get("roic")
    if not is_financial and roic is not None:
        if roic >= 15:
            insights.append(
                {
                    "tone": "positive",
                    "text": f"ROIC 达 {roic:.1f}%，显著高于典型资本成本，主业再投资正在创造价值。",
                }
            )
        elif roic < 5 and (net_income or 0) > 0:
            insights.append(
                {
                    "tone": "caution",
                    "text": f"ROIC 仅 {roic:.1f}%，投入资本回报偏低，需关注资本开支效率与定价能力。",
                }
            )
        if roe is not None and roe - roic > 10:
            insights.append(
                {
                    "tone": "neutral",
                    "text": f"ROE {roe:.1f}% 明显高于 ROIC {roic:.1f}%，差额主要来自杠杆与低账面权益，回报质量需结合资本结构判断。",
                }
            )
    ccc = ratio.get("ccc")
    ccc_prev = previous.get("ccc") if previous else None
    if ccc is not None and ccc_prev is not None:
        ccc_delta = ccc - ccc_prev
        if ccc_delta <= -5:
            insights.append(
                {
                    "tone": "positive",
                    "text": f"现金转换周期缩短 {abs(ccc_delta):.0f} 天至 {ccc:.0f} 天，营运资金效率改善。",
                }
            )
        elif ccc_delta >= 10:
            insights.append(
                {
                    "tone": "caution",
                    "text": f"现金转换周期拉长 {ccc_delta:.0f} 天至 {ccc:.0f} 天，存货或应收占用上升。",
                }
            )
    if not is_financial and rows and len(rows) > 1:
        receivables_now = rows[-1].get("receivables")
        receivables_prev = rows[-2].get("receivables")
        revenue_now = rows[-1].get("revenue")
        revenue_prev = rows[-2].get("revenue")
        if all(value is not None and value > 0 for value in (receivables_now, receivables_prev, revenue_now, revenue_prev)):
            receivable_growth = (receivables_now / receivables_prev - 1) * 100
            revenue_growth = (revenue_now / revenue_prev - 1) * 100
            if receivable_growth > revenue_growth + 10 and receivable_growth > 10:
                insights.append(
                    {
                        "tone": "caution",
                        "text": f"应收账款同比 {receivable_growth:+.0f}%，快于营收 {revenue_growth:+.0f}%，关注回款质量与收入确认节奏。",
                    }
                )
    if allocation and allocation.get("latest"):
        latest_alloc = allocation["latest"]
        payout = latest_alloc.get("payout_of_fcf")
        if payout is not None:
            if payout > 100:
                insights.append(
                    {
                        "tone": "caution",
                        "text": f"分红与回购合计相当于自由现金流的 {payout:.0f}%，股东回报已超过当年 FCF 创造能力。",
                    }
                )
            elif payout >= 40:
                insights.append(
                    {
                        "tone": "positive",
                        "text": f"分红与回购合计占自由现金流 {payout:.0f}%，资本回报与再投资保持平衡。",
                    }
                )
            elif payout < 40:
                insights.append(
                    {
                        "tone": "neutral",
                        "text": f"股东回报仅占自由现金流 {payout:.0f}%，现金更多留存表内或用于再投资。",
                    }
                )
    if trend:
        years = trend.get("years") or 0
        revenue_cagr = trend.get("revenue_cagr")
        fcf_cagr = trend.get("fcf_cagr")
        if revenue_cagr is not None and years >= 2:
            if revenue_cagr >= 15:
                insights.append(
                    {
                        "tone": "positive",
                        "text": f"近 {years} 年营收 CAGR {revenue_cagr:.1f}%，成长动能强劲"
                        + (f"，FCF CAGR {fcf_cagr:.1f}%。" if fcf_cagr is not None else "。"),
                    }
                )
            elif revenue_cagr <= 0:
                insights.append(
                    {
                        "tone": "caution",
                        "text": f"近 {years} 年营收 CAGR {revenue_cagr:.1f}%，增长停滞或收缩。",
                    }
                )
    rule40 = ratio.get("rule_of_40")
    if not is_financial and rule40 is not None and rule40 >= 40:
        insights.append(
            {
                "tone": "positive",
                "text": f"营收增速与 FCF 利润率合计 {rule40:.0f} 个百分点，达到 Rule of 40 的优质增长标准。",
            }
        )
    if is_financial:
        insights.append(
            {
                "tone": "neutral",
                "text": "银行、保险的现金流与资产负债结构特殊，FCF 与应计质量不宜直接套用；应重点观察 ROE、净息差、拨备与资本充足率。",
            }
        )
    return insights[:12]


async def statements(symbol: str, *, industry: str = "") -> dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    cik = await sec.cik_for(symbol)
    if not cik:
        return {
            "symbol": symbol,
            "available": False,
            "message": "SEC EDGAR 未收录该标的，可能为 ETF、ADR 或未在美国注册。",
            "source": "sec_edgar_companyfacts",
            "as_of": datetime.now(ET).isoformat(timespec="seconds"),
        }
    facts = await _companyfacts(cik)
    annual_rows = _build_rows(facts, quarterly=False)
    quarterly_rows = _build_rows(facts, quarterly=True)
    annual_ratios = _annual_ratios(annual_rows)
    quarterly_ratios = _annual_ratios(quarterly_rows, days=91)
    is_financial = any(hint in (industry or "") for hint in FINANCIAL_HINTS)
    if not is_financial and annual_rows:
        latest = annual_rows[-1]
        is_financial = (
            latest.get("gross_profit") is None
            and latest.get("current_assets") is None
            and bool(latest.get("total_assets"))
            and latest.get("equity") is not None
        )
    trend = _trend(annual_rows, annual_ratios) if annual_rows else None
    allocation = _capital_allocation(annual_rows) if annual_rows else None
    insights = _statement_insights(
        annual_rows,
        annual_ratios,
        is_financial=is_financial,
        trend=trend,
        allocation=allocation,
    )
    return {
        "symbol": symbol,
        "cik": cik,
        "company": facts.get("entity"),
        "currency": "USD",
        "available": bool(annual_rows),
        "is_financial": is_financial,
        "annual": {"rows": annual_rows, "ratios": annual_ratios},
        "quarterly": {"rows": quarterly_rows, "ratios": quarterly_ratios},
        "trend": trend,
        "capital_allocation": allocation,
        "insights": insights,
        "message": "" if annual_rows else "companyfacts 中未找到可识别的美国 GAAP 财务科目。",
        "source": "sec_edgar_companyfacts",
        "as_of": datetime.now(ET).isoformat(timespec="seconds"),
    }


async def cashflow(symbol: str) -> dict[str, Any]:
    payload = await statements(symbol)
    rows = (payload.get("annual") or {}).get("rows") or []
    items = [
        {
            "date": row["date"],
            "ocf": row.get("ocf"),
            "capex": row.get("capex"),
            "fcf": row.get("fcf"),
            "revenue": row.get("revenue"),
            "net_income": row.get("net_income"),
        }
        for row in rows
        if row.get("ocf") is not None or row.get("fcf") is not None
    ]
    return {"items": items, "source": "sec_edgar"}


_WS_RE = re.compile(r"[\s\u00a0\u200b\u200c\u200d\ufeff]+")
_PAGE_HEADER_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&'.,\- ]{0,60}\|\s*20\d{2}\s+Form\s+10-[KQ](?:/A)?\s*\|\s*\d+\s*",
    re.I,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_CLAUSE_SPLIT = re.compile(r"[.!?]")


def _html_text(raw: bytes, *, drop_tables: bool = False) -> str:
    if not raw or raw[:5] == b"%PDF-":
        return ""
    cleaned = re.sub(rb"^\s*<\?xml[^>]*\?>", b"", raw, count=1)
    try:
        document = lxml_html.document_fromstring(
            cleaned, parser=lxml_html.HTMLParser(recover=True, huge_tree=True)
        )
    except (ValueError, lxml_etree.ParserError):
        return ""
    drop_xpath = "//script | //style" + (" | //table" if drop_tables else "")
    for node in document.xpath(drop_xpath):
        node.drop_tree()
    try:
        text = document.text_content()
    except (ValueError, UnicodeDecodeError):
        return ""
    text = text.replace("Table of Contents", " ")
    text = _PAGE_HEADER_RE.sub(" ", text)
    text = re.sub(r"(?<=[a-z0-9])\.(?=[A-Z])", ". ", text)
    return _WS_RE.sub(" ", text).strip()


_ITEM_TOKEN_RE = re.compile(r"\bitem\s*\d+[a-z]?\b", re.I)
_PAGE_ITEM_RE = re.compile(r"\d{1,3}\s*item\s*\d", re.I)
_CROSSREF_RE = re.compile(
    r"for (?:a )?(?:discussion|additional information)|refer to|see (?:item|note)|"
    r"described (?:below|above|in)|included (?:below|above|in)|in this (?:annual|quarterly) report|"
    r"under (?:item|the heading)|set forth",
    re.I,
)


def _looks_like_toc(head: str) -> bool:
    return len(_ITEM_TOKEN_RE.findall(head[:500])) >= 3 or bool(_PAGE_ITEM_RE.search(head[:500]))


def _looks_like_crossref(head: str) -> bool:
    stripped = head.lstrip()
    if stripped[:1] in {",", ".", ";", ":", "”", "’", "'", '"', ")", "]", "–", "—", "-"}:
        return True
    return bool(_CROSSREF_RE.search(head[:80]))


def _extract_section(
    text: str,
    patterns: tuple[tuple[str, ...], tuple[str, ...]],
    *,
    min_len: int = 1800,
    cap: int = 140_000,
) -> str:
    if not text:
        return ""
    start_patterns, end_patterns = patterns
    end_res = tuple(re.compile(pattern, re.I) for pattern in end_patterns)
    best: tuple[int, int, int] | None = None
    for start_pattern in start_patterns:
        for match in re.finditer(start_pattern, text, re.I):
            start = match.end()
            if start >= len(text):
                continue
            head = text[start : start + 520]
            if _looks_like_toc(head) or _looks_like_crossref(head):
                continue
            end = len(text)
            for end_re in end_res:
                found = end_re.search(text, start + 600)
                if found and found.start() < end:
                    end = found.start()
            span = end - start
            # A table-of-contents hit ends at the next item heading; the real body wins on length.
            if span >= min_len and (best is None or span > best[0]):
                best = (span, start, end)
    if not best:
        return ""
    return text[best[1] : best[2]][:cap]


def _mda_patterns(form: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    form = (form or "").upper()
    if form.startswith("10-Q"):
        return (
            (
                r"item\s*2\s*[.\-:—]?\s*management[\u2019']?s\s+discussion",
                r"management[\u2019']?s\s+discussion\s+and\s+analysis(?:\s+of\s+financial\s+condition\s+and\s+results\s+of\s+operations)?",
            ),
            (
                r"item\s*3\s*[.\-:—]?\s*quantitative",
                r"item\s*4\s*[.\-:—]?\s*controls",
            ),
        )
    if form.startswith("20-F"):
        return (
            (r"operating\s+and\s+financial\s+review(?:s)?\s+and\s+prospects",),
            (r"directors,?\s+senior\s+management\s+and\s+employees",),
        )
    return (
        (
            r"item\s*7\s*[.\-:—]?\s*management[\u2019']?s\s+discussion\s+and\s+analysis",
            r"management[\u2019']?s\s+discussion\s+and\s+analysis(?:\s+of\s+financial\s+condition\s+and\s+results\s+of\s+operations)?",
        ),
        (
            r"item\s*7a\s*[.\-:—]?\s*quantitative",
            r"item\s*8\s*[.\-:—]?\s*financial\s+statements",
        ),
    )


def _risk_patterns(form: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    form = (form or "").upper()
    if form.startswith("10-Q"):
        return (
            (r"item\s*1a\s*[.\-:—]?\s*risk\s+factors", r"risk\s+factors"),
            (
                r"item\s*2\s*[.\-:—]?\s*unregistered",
                r"item\s*5\s*[.\-:—]?\s*other\s+information",
                r"item\s*6\s*[.\-:—]?\s*exhibits",
            ),
        )
    if form.startswith("20-F"):
        return (
            (r"risk\s+factors",),
            (r"item\s*4\s*[.\-:—]?\s*information\s+on\s+the\s+company",),
        )
    return (
        (r"item\s*1a\s*[.\-:—]?\s*risk\s+factors", r"risk\s+factors"),
        (
            r"item\s*1b\s*[.\-:—]?\s*unresolved",
            r"item\s*2\s*[.\-:—]?\s*properties",
        ),
    )


@lru_cache(maxsize=50_000)
def _syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


POSITIVE = frozenset(
    """accelerate accelerated accelerating achieve achieved achievement advantage advantageous attractive
    benefit beneficial best better boost boosted collaboration confidence confident consistent continue
    continued strong stronger strongest deliver delivered demand efficiency efficient enhance enhanced
    exceed exceeded exceeding excellent expand expanded expanding expansion favorable gain gained gains
    good great grow growing grown growth healthy high higher highest improve improved improvement
    improving increase increased increasing innovation innovative leadership leading loyalty momentum
    opportunity opportunities optimistic outperform outperformed positive profit profitable progress
    record resilient robust solid strength strengthen strengthened success successful superior
    sustainable transform transformation upside valuable win winning""".split()
)
NEGATIVE = frozenset(
    """adverse adversely allegation allegations bankruptcy breach challenging challenge damage decline
    declined declining decrease decreased default deterioration difficult difficulty diminish diminished
    disadvantage disruption disruptive dispute disputes downturn drop dropped erosion fail failed failure
    falling fines fluctuation harm harmed headwind hurt impairment impairments inability insolvency
    lawsuit litigation loss losses negative penalty recession restructuring sanction sanctions shortage
    slowdown soften softness suffer suffered tariff tariffs tension tensions threat threats unfavorable
    volatility volatile weak weakness weaken weakened worse worsen worsening writedown writeoff
    cyberattack""".split()
)
UNCERTAINTY = frozenset(
    """approximately assume assumed assumption believe believes could depend depends estimate estimated
    expect expected fluctuate may might possible potentially probable seek should uncertain uncertainty
    unlikely vary variability volatility anticipate anticipated intend likely""".split()
)

OUTLOOK_CUES = (
    " will ",
    " expect",
    " anticipate",
    " outlook",
    " forecast",
    " guidance",
    " intend",
    " plan to ",
    " going forward",
    " next year",
    " long-term",
    " continue to",
)
OUTLOOK_SOFT_CUES = (" believe", " plan ", " may ", " could ")
DISCLAIMER_RE = re.compile(
    r"no assurance|actual results|forward-looking|undue reliance|not undertake|could differ|may differ|"
    r"not necessarily|does not represent|subject to (?:change|risk)|past performance|this analysis|"
    r"\bASU\s+20\d{2}-\d{2}\b|accounting standards update|\(\w\)\s*[A-Z]",
    re.I,
)

THEME_DEFS = (
    ("ai", "AI 与算力", r"\bartificial intelligence\b|\bmachine learning\b|\bgenerative ai\b|\bgen\s?ai\b|\bai\b|\bgpu\b|\baccelerated computing\b|\bdata cent(er|re)\b"),
    ("cloud", "云计算", r"\bcloud\b|\bsaas\b|\bsoftware as a service\b"),
    ("tariffs_trade", "关税与贸易", r"\btariff|\btrade polic|\btrade agreement|\bexport control|\btrade restriction|\bimport dut|\btrade war\b"),
    ("inflation_pricing", "通胀与定价", r"\binflation|\bpricing power\b|\bprice increases?\b|\binput costs?\b|\bdisinflation"),
    ("supply_chain", "供应链", r"\bsupply chain|\bsuppliers?\b|\blogistic|\bcomponent shortage|\bmanufactur"),
    ("cyber", "网络安全与隐私", r"\bcybersecurity|\bcyber attack|\bdata breach|\bprivacy\b|\bdata protection\b"),
    ("regulation", "监管与合规", r"\bregulat|\bcompliance\b|\bantitrust|\blegislation|\bgovernment"),
    ("competition", "竞争格局", r"\bcompetit|\bcompetitors?\b|\bmarket share\b|\bpricing pressure\b"),
    ("china_geo", "中国与地缘", r"\bchina\b|\bgeopolitic|\btaiwan\b|\bukraine\b|\bsanction"),
    ("climate", "气候与能源", r"\bclimate\b|\bcarbon\b|\brenewable\b|\bemission|\benergy transition\b"),
    ("capital_return", "股东回报", r"\bdividend|\bbuyback|\bshare repurchase|\bcapital return\b"),
    ("restructuring", "重组与降本", r"\brestructur|\bcost reduction|\blayoff|\bworkforce reduction|\bimpairment"),
    ("fx", "汇率与外汇", r"\bforeign exchange|\bcurrency\b|\bfx\b|\bexchange rate"),
    ("labor", "人力与用工", r"\bemployees?\b|\bworkforce|\btalent\b|\blabor\b|\bunion\b"),
    ("liquidity", "流动性与融资", r"\bliquidity|\bcredit facility|\bcovenant|\bcash flow from operations\b"),
)
THEME_PATTERNS = tuple((key, label, re.compile(pattern, re.I)) for key, label, pattern in THEME_DEFS)


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text)]
    return [sentence for sentence in sentences if len(sentence.split()) >= 4]


def _tone_label(net: float) -> str:
    if net >= 0.12:
        return "偏乐观"
    if net <= -0.12:
        return "偏谨慎"
    return "中性"


def _flesch_label(score: float) -> str:
    if score >= 60:
        return "易读"
    if score >= 45:
        return "适中"
    if score >= 30:
        return "偏难"
    return "晦涩"


def _analyze_text(text: str) -> dict[str, Any]:
    lower = text.lower()
    words = _WORD_RE.findall(text)
    word_count = len(words)
    sentences = _split_sentences(text)
    sentence_count = max(1, len(sentences))
    syllables = sum(_syllables(word.lower()) for word in words) or word_count
    if word_count:
        flesch = 206.835 - 1.015 * (word_count / sentence_count) - 84.6 * (syllables / word_count)
    else:
        flesch = 0.0

    counts = Counter(re.findall(r"[a-z]+", lower))
    positive = sum(counts[word] for word in POSITIVE if counts.get(word))
    negative = sum(counts[word] for word in NEGATIVE if counts.get(word))
    uncertain = sum(counts[word] for word in UNCERTAINTY if counts.get(word))
    denominator = word_count or 1
    net = (positive - negative) / (positive + negative) if positive + negative else 0.0

    themes = []
    for key, label, pattern in THEME_PATTERNS:
        count = len(pattern.findall(lower))
        if count:
            themes.append(
                {
                    "key": key,
                    "label": label,
                    "count": count,
                    "per10k": round(count / denominator * 10000, 2),
                }
            )
    themes.sort(key=lambda item: -item["count"])

    return {
        "stats": {
            "words": word_count,
            "sentences": len(sentences),
            "avg_sentence_words": round(word_count / sentence_count, 1),
            "flesch": round(flesch, 1),
            "flesch_label": _flesch_label(flesch),
        },
        "tone": {
            "positive": round(positive / denominator * 10000, 2),
            "negative": round(negative / denominator * 10000, 2),
            "uncertainty": round(uncertain / denominator * 10000, 2),
            "net": round(net, 3),
            "label": _tone_label(net),
        },
        "themes": themes,
        "sentences": sentences,
    }


def _sentence_tone(sentence: str) -> str:
    tokens = set(re.findall(r"[a-z]+", sentence.lower()))
    positive = len(tokens & POSITIVE)
    negative = len(tokens & NEGATIVE)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _sentence_theme(sentence: str) -> str | None:
    for _, label, pattern in THEME_PATTERNS:
        if pattern.search(sentence):
            return label
    return None


ROLE_DEFS = (
    ("outlook", "管理层展望", re.compile(
        r"\b(?:expect|expects|expected|anticipate|anticipates|forecast|outlook|guidance|intend|"
        r"plan to|will|going forward|next (?:quarter|year)|fiscal year|we believe)\b", re.I)),
    ("liquidity", "流动性与资本资源", re.compile(
        r"\b(?:liquidity|cash and cash equivalents|cash flow from operations|free cash flow|"
        r"working capital|credit facility|revolving|borrowing|covenant|debt matur|repayment)\b", re.I)),
    ("capital", "资本配置", re.compile(
        r"\b(?:dividend\w*|repurchas\w*|buyback\w*|capital expenditure\w*|capex|"
        r"acquisition\w*|merger\w*|investment\w*)\b", re.I)),
    ("accounting", "关键会计估计", re.compile(
        r"\b(?:critical accounting|accounting estimate|accounting estimates|accounting judgment|"
        r"assumption|assumptions|impairment|valuation allowance|useful life|provision|"
        r"uncertain tax position)\b", re.I)),
    ("results", "经营表现", re.compile(
        r"\b(?:revenue|revenues|net sales|sales|gross margin|gross profit|operating income|"
        r"operating expenses|net income|earnings per share|diluted eps|segment|segments)\b", re.I)),
    ("risk", "风险与不确定", re.compile(
        r"\b(?:risk|risks|uncertain|uncertainty|subject to|adverse|volatil|macroeconomic|"
        r"geopolitical|supply chain|competition|tariff|regulatory)\b", re.I)),
)
ROLE_LABELS = {key: label for key, label, _ in ROLE_DEFS}
ROLE_LABELS["other"] = "其他表述"
GUIDANCE_METRICS = (
    ("营收", re.compile(r"\b(?:revenue|revenues|net sales|sales)\b", re.I)),
    ("每股收益", re.compile(r"\b(?:earnings per share|eps|diluted earnings per share)\b", re.I)),
    ("毛利率", re.compile(r"\bgross margin\b", re.I)),
    ("营业利润率", re.compile(r"\boperating margin\b", re.I)),
    ("自由现金流", re.compile(r"\bfree cash flow\b", re.I)),
    ("资本开支", re.compile(r"\b(?:capital expenditure|capital expenditures|capex)\b", re.I)),
    ("税率", re.compile(r"\b(?:tax rate|effective tax rate)\b", re.I)),
)
GUIDANCE_PERIOD = re.compile(
    r"\b(?:full[- ]year|fiscal (?:year )?20\d{2}|fiscal 20\d{2}|first quarter|second quarter|"
    r"third quarter|fourth quarter|Q[1-4]|next (?:quarter|year)|20\d{2})\b", re.I
)
NUMBER_TEXT = re.compile(
    r"(?:\$\s*)?\d+(?:\.\d+)?\s*(?:%|percent|percentage points?|basis points?|"
    r"billion|million|bn|mn|x)\b(?!\w)|(?:\$\s*)?\d+(?:\.\d+)?\s*(?:to|-|–)\s*"
    r"(?:\$\s*)?\d+(?:\.\d+)?\s*(?:%|percent|billion|million|bn|mn|x)\b",
    re.I,
)
MDA_SUBSECTION_DEFS = (
    ("results", "经营业绩", re.compile(r"\bresults of operations", re.I)),
    ("products", "产品与服务表现", re.compile(r"\bproducts and services performance", re.I)),
    ("segments", "分部表现", re.compile(r"\bsegment(?:s| operating performance| results| performance| discussion| information)", re.I)),
    ("liquidity", "流动性与资本资源", re.compile(r"\bliquidity and capital resources", re.I)),
    ("capital", "资本资源", re.compile(r"\bcapital resources", re.I)),
    ("critical", "关键会计估计", re.compile(r"\bcritical accounting (?:estimates|policies|judgments)", re.I)),
    ("contractual", "合同义务", re.compile(r"\bcontractual obligations", re.I)),
    ("non_gaap", "非 GAAP 指标", re.compile(r"\bnon[- ]gaap", re.I)),
    ("accounting_new", "新会计公告", re.compile(r"\b(?:recently issued|recently adopted|new accounting)", re.I)),
    ("outlook", "经营展望", re.compile(r"\b(?:business outlook|financial outlook|company outlook|outlook)", re.I)),
    ("market_risk", "市场风险", re.compile(r"\bquantitative and qualitative disclosures? about market risk", re.I)),
)
SECTION_ROLE = {
    "results": "results",
    "products": "results",
    "liquidity": "liquidity",
    "capital": "liquidity",
    "critical": "accounting",
    "contractual": "liquidity",
    "segments": "results",
    "non_gaap": "results",
    "accounting_new": "accounting",
    "outlook": "outlook",
    "market_risk": "risk",
}


def _sentence_hash(sentence: str) -> str:
    normalized = " ".join(sorted(re.findall(r"[a-z0-9]+", sentence.lower())))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


MDA_HEADING_NAMES = (
    "Results of Operations",
    "Products and Services Performance",
    "Segment Operating Performance",
    "Liquidity and Capital Resources",
    "Capital Resources",
    "Critical Accounting Estimates",
    "Contractual Obligations",
    "Business Outlook",
    "Financial Outlook",
    "Quantitative and Qualitative Disclosures About Market Risk",
)


def _readable_fragment(sentence: str) -> str:
    # Flattened filing text often joins a heading and its first paragraph ("ResourcesThe Company").
    value = re.sub(r"(?<=[a-z]{2})(?=[A-Z][a-z])", ". ", sentence).strip()
    for heading in MDA_HEADING_NAMES:
        value = re.sub(rf"^{re.escape(heading)}(?:\.\s*|\s+)", "", value, flags=re.I)
    # Collapse a heading that is immediately repeated by its paragraph ("Services. Services ...").
    value = re.sub(r"^([A-Z][^.!?]{2,70}?)\.\s+\1(?=\s)", r"\1", value, flags=re.I)
    return value.strip()


def _sentence_role(sentence: str) -> str:
    lower = f" {sentence.lower()} "
    best, best_score = "other", 0
    for index, (key, _, pattern) in enumerate(ROLE_DEFS):
        score = len(pattern.findall(lower))
        if not score:
            continue
        if key == "outlook":
            score += 2 if re.search(r"\b(?:expect|anticipate|forecast|outlook|guidance|plan to|will|going forward)\b", lower) else 0
        if key == "risk" and not re.search(r"\b(?:risk|uncertain|subject to|adverse|volatil)\b", lower):
            score -= 1
        weighted = score * (1.0 - index * 0.03)
        if weighted > best_score:
            best, best_score = key, weighted
    return best


def _key_sentences(sentences: list[str], section_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    section_map = section_map or {}
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in sentences[:1600]:
        length = len(sentence.split())
        if not 11 <= length <= 78:
            continue
        if "Form 10-K" in sentence or "Form 10-Q" in sentence or "|" in sentence:
            continue
        if DISCLAIMER_RE.search(sentence):
            continue
        if re.search(r"\b(?:table of contents|incorporated by reference|exhibit\s+\d)\b", sentence, re.I):
            continue
        digest = _sentence_hash(sentence)
        if digest in seen:
            continue
        seen.add(digest)
        role = _sentence_role(sentence)
        numbers = len(NUMBER_TEXT.findall(sentence))
        financial = len(FINANCIAL_SENTENCE_RE.findall(sentence))
        themes = sum(1 for _, _, pattern in THEME_PATTERNS if pattern.search(sentence))
        role_weight = {"results": 1.2, "liquidity": 1.5, "capital": 1.45, "outlook": 1.35, "accounting": 1.15, "risk": .55}.get(role, .35)
        score = role_weight + min(numbers, 5) * .55 + min(financial, 4) * .35 + min(themes, 3) * .28
        if re.search(r"\$|%|billion|million|basis points", sentence, re.I):
            score += .7
        if _sentence_tone(sentence) != "neutral":
            score += .3
        if length > 60:
            score -= .25
        if re.search(r"\b(?:we|our|management)\b", sentence, re.I):
            score += .2
        candidates.append({
            "hash": digest,
            "text": _readable_fragment(sentence[:420]),
            "role": role,
            "role_label": ROLE_LABELS[role],
            "topic": _sentence_theme(sentence),
            "tone": _sentence_tone(sentence),
            "section": section_map.get(digest, ""),
            "score": round(score, 3),
        })
    candidates.sort(key=lambda item: (-item["score"], item["text"]))
    selected: list[dict[str, Any]] = []
    role_counts: Counter[str] = Counter()
    for item in candidates:
        if role_counts[item["role"]] >= 3:
            continue
        selected.append(item)
        role_counts[item["role"]] += 1
        if len(selected) >= 16:
            break
    return selected


def _guidance_items(sentences: list[str], limit: int = 6) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in sentences:
        if not 8 <= len(sentence.split()) <= 75 or DISCLAIMER_RE.search(sentence):
            continue
        if not re.search(r"\b(?:expect|expects|expected|anticipate|anticipates|forecast|guidance|outlook|plan to|intend|will)\b", sentence, re.I):
            continue
        values = [match.group(0).strip() for match in NUMBER_TEXT.finditer(sentence)]
        if not values:
            continue
        metric = next((label for label, pattern in GUIDANCE_METRICS if pattern.search(sentence)), "")
        period = next((match.group(0) for match in GUIDANCE_PERIOD.finditer(sentence)), "")
        if not metric:
            continue
        digest = _sentence_hash(sentence)
        if digest in seen:
            continue
        seen.add(digest)
        items.append({
            "metric": metric or "量化指引",
            "period": period,
            "values": values[:3],
            "text": _readable_fragment(sentence[:380]),
            "tone": _sentence_tone(sentence),
        })
        if len(items) >= limit:
            break
    return items


def _mda_subsections(text: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not text:
        return [], {}
    candidates: list[tuple[int, int, str, str]] = []
    for key, label, pattern in MDA_SUBSECTION_DEFS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 24):match.start()]
            if match.start() > 24 and not re.search(r"[.!?]\s*$", prefix):
                continue
            head = text[match.end():match.end() + 180]
            if _looks_like_toc(head):
                continue
            candidates.append((match.start(), match.end(), key, label))
    candidates.sort()
    filtered: list[tuple[int, int, str, str]] = []
    for candidate in candidates:
        if filtered and candidate[0] - filtered[-1][0] < 180:
            continue
        filtered.append(candidate)
    sections: list[dict[str, Any]] = []
    section_map: dict[str, str] = {}
    total_words = max(1, len(_WORD_RE.findall(text)))
    for position, (_, end, key, label) in enumerate(filtered):
        start = end
        stop = filtered[position + 1][0] if position + 1 < len(filtered) else len(text)
        content = text[start:stop][:60_000]
        words = len(_WORD_RE.findall(content))
        if words < 24:
            continue
        metrics = _analyze_text(content)
        sentences = metrics.pop("sentences")
        for sentence in sentences:
            section_map[_sentence_hash(sentence)] = label
        top = _key_sentences(sentences)
        excerpt = top[0] if top else None
        sections.append({
            "key": key,
            "label": label,
            "words": words,
            "share": round(words / total_words * 100, 1),
            "tone": metrics["tone"]["label"],
            "tone_net": metrics["tone"]["net"],
            "themes": metrics["themes"][:3],
            "excerpt": excerpt["text"] if excerpt else "",
        })
    return sections, section_map


def _management_brief(key_sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = ("results", "liquidity", "capital", "outlook", "accounting", "risk")
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for role in priority:
        item = next((entry for entry in key_sentences if entry["role"] == role and entry["hash"] not in used), None)
        if not item:
            continue
        used.add(item["hash"])
        result.append({
            "label": ROLE_LABELS.get(role, "关键表述"),
            "role": role,
            "tone": item["tone"],
            "text": item["text"],
            "topic": item["topic"],
        })
    if not result:
        for item in key_sentences[:3]:
            result.append({
                "label": item["role_label"],
                "role": item["role"],
                "tone": item["tone"],
                "text": item["text"],
                "topic": item["topic"],
            })
    return result[:6]


def _outlooks(sentences: list[str], limit: int = 6) -> list[dict[str, Any]]:
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        length = len(sentence.split())
        if not 12 <= length <= 70:
            continue
        if "Form 10-K" in sentence or "Form 10-Q" in sentence or "|" in sentence:
            continue
        if DISCLAIMER_RE.search(sentence):
            continue
        if re.search(r"\b(have not|has not|may not|could not|will not|no assurance)\b", sentence, re.I):
            continue
        if re.search(r"\blitigation|lawsuit|court|appeal|settlement|investigation\b", sentence, re.I):
            continue
        lower = f" {sentence.lower()} "
        hits = sum(1 for cue in OUTLOOK_CUES if cue in lower)
        if not hits:
            continue
        score = hits * 2 + (0.5 if any(cue in lower for cue in OUTLOOK_SOFT_CUES) else 0.0)
        score += 0.5 if re.search(r"\d", sentence) else 0.0
        score += 0.5 if " we " in lower else 0.0
        tone = _sentence_tone(sentence)
        score += 0.8 if tone == "positive" else -1.0 if tone == "negative" else 0.0
        scored.append((score, index, sentence))
    scored.sort(key=lambda item: -item[0])
    picks: list[tuple[float, int, str]] = []
    seen: set[str] = set()
    for item in scored:
        signature = item[2][:48].lower()
        if signature in seen:
            continue
        seen.add(signature)
        picks.append(item)
        if len(picks) >= limit:
            break
    picks.sort(key=lambda item: item[1])
    return [
        {"text": _readable_fragment(sentence[:360]), "tone": _sentence_tone(sentence), "topic": _sentence_theme(sentence)}
        for _, _, sentence in picks
    ]


RISK_CUES = (" risk", " could", " may ", " adversely", " harm", " negative", " uncertain", " depend", " subject to", " expose", " impact")


def _risk_excerpts(sentences: list[str], limit: int = 4) -> list[dict[str, str]]:
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences[:900]):
        length = len(sentence.split())
        if not 12 <= length <= 80:
            continue
        if "Form 10-K" in sentence or "Form 10-Q" in sentence or "|" in sentence:
            continue
        if DISCLAIMER_RE.search(sentence):
            continue
        tokens = set(re.findall(r"[a-z]+", sentence.lower()))
        hits = len(tokens & NEGATIVE)
        if not hits:
            continue
        lower = f" {sentence.lower()} "
        cue_hits = sum(1 for cue in RISK_CUES if cue in lower)
        score = hits * 1.5 + min(3, cue_hits) * 0.4
        score += 0.3 if re.search(r"\d", sentence) else 0.0
        scored.append((score, index, sentence))
    scored.sort(key=lambda item: -item[0])
    picks: list[dict[str, str]] = []
    topic_counts: Counter[str] = Counter()
    seen: set[str] = set()
    for score, index, sentence in scored:
        signature = sentence[:48].lower()
        if signature in seen:
            continue
        topic = _sentence_theme(sentence) or "一般风险"
        if topic_counts[topic] >= 2:
            continue
        seen.add(signature)
        topic_counts[topic] += 1
        picks.append({"text": _readable_fragment(sentence[:400]), "topic": topic, "tone": "negative"})
        if len(picks) >= limit:
            break
    return picks


def _risk_excerpt(sentences: list[str]) -> str:
    best = ""
    best_score = -1
    for sentence in sentences[:600]:
        length = len(sentence.split())
        if not 12 <= length <= 65:
            continue
        if "Form 10-K" in sentence or "Form 10-Q" in sentence or "|" in sentence:
            continue
        tokens = set(re.findall(r"[a-z]+", sentence.lower()))
        score = len(tokens & NEGATIVE)
        if score > best_score:
            best_score = score
            best = sentence
    return _readable_fragment(best[:420])


FINANCIAL_SENTENCE_RE = re.compile(
    r"revenue|sales|margin|income|earnings|cash flow|cost|expense|backlog|billings|subscription|"
    r"free cash|operating profit|gross profit|eps|return on",
    re.I,
)


def _numeric_excerpt(sentences: list[str]) -> str:
    best = ""
    best_score = -1.0
    for sentence in sentences[:1200]:
        length = len(sentence.split())
        if not 10 <= length <= 55:
            continue
        if "Form 10-K" in sentence or "Form 10-Q" in sentence or "|" in sentence:
            continue
        if DISCLAIMER_RE.search(sentence):
            continue
        if not re.search(r"\d", sentence) or not FINANCIAL_SENTENCE_RE.search(sentence):
            continue
        if re.search(r"\b(\w{3,})\1\b", sentence) or re.search(r"[a-z]\.[A-Za-z]", sentence):
            continue
        score = len(re.findall(r"\d", sentence)) * 0.5
        score += 2.0 if re.search(r"%|\$|billion|million|basis points", sentence, re.I) else 0.0
        score += 1.0 if _sentence_tone(sentence) == "positive" else 0.0
        score += 0.5 if re.search(r"grew|increased|improved|expanded|declined|decreased", sentence, re.I) else 0.0
        if score > best_score:
            best_score = score
            best = sentence
    return _readable_fragment(best[:330])


def _mda_highlights(metrics: dict[str, Any], sentences: list[str], outlooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tone = metrics.get("tone") or {}
    stats = metrics.get("stats") or {}
    themes = metrics.get("themes") or []
    net = tone.get("net") or 0.0
    highlights: list[dict[str, Any]] = [
        {
            "label": "语气概览",
            "tone": "positive" if net >= 0.12 else "caution" if net <= -0.12 else "neutral",
            "text": (
                f"全篇 {stats.get('words', 0):,} 词、平均句长 {stats.get('avg_sentence_words', 0):.1f} 词，"
                f"正面 {tone.get('positive', 0):.1f} / 负面 {tone.get('negative', 0):.1f} 次每万词，"
                f"净语气「{tone.get('label', '中性')}」。"
            ),
        }
    ]
    if themes:
        top = themes[:3]
        highlights.append(
            {
                "label": "核心议题",
                "tone": "neutral",
                "text": "管理层讨论集中于 "
                + "、".join(f"{item['label']}（{item['count']} 次）" for item in top)
                + "。",
            }
        )
    if outlooks:
        topics = []
        for item in outlooks:
            if item.get("topic") and item["topic"] not in topics:
                topics.append(item["topic"])
        highlights.append(
            {
                "label": "前瞻表述",
                "tone": "neutral",
                "text": f"捕捉到 {len(outlooks)} 条明确的前瞻性表述"
                + (f"，涉及{'、'.join(topics[:3])}等议题。" if topics else "，以经营计划与业绩指引为主。"),
            }
        )
    numeric = _numeric_excerpt(sentences)
    if numeric:
        highlights.append({"label": "关键数据", "tone": "neutral", "text": numeric})
    return highlights


def _section_payload(text: str, label: str) -> dict[str, Any]:
    metrics = _analyze_text(text)
    sentences = metrics.pop("sentences")
    payload: dict[str, Any] = {"label": label, "chars": len(text), **metrics}
    sections, section_map = _mda_subsections(text) if label == "MD&A" else ([], {})
    keys = _key_sentences(sentences, section_map)
    payload["_hashes"] = sorted({_sentence_hash(sentence) for sentence in sentences})
    payload["_key_sentences"] = keys
    if label == "MD&A":
        outlook = _outlooks(sentences)
        brief = _management_brief(keys)
        guidance = _guidance_items(sentences)
        payload["outlook"] = outlook
        payload["management_brief"] = brief
        payload["guidance"] = guidance
        payload["sections"] = sections
        payload["key_statements"] = [
            {key: item[key] for key in ("role", "role_label", "tone", "topic", "text", "section")}
            for item in keys[:10]
        ]
        payload["highlights"] = [
            {"label": item["label"], "tone": item["tone"], "text": item["text"]}
            for item in brief
        ] or _mda_highlights(metrics, sentences, outlook)
    else:
        excerpts = _risk_excerpts(sentences)
        payload["excerpts"] = excerpts
        payload["excerpt"] = excerpts[0]["text"] if excerpts else _risk_excerpt(sentences)
    return payload


async def _analyze_filing(item: dict[str, Any]) -> dict[str, Any]:
    accession = item.get("accession") or item.get("url")
    key = f"sec:mda:v15:{accession}"

    async def factory() -> dict[str, Any]:
        raw = await _sec_bytes(item["url"])
        text = _html_text(raw, drop_tables=True)
        mda_text = _extract_section(text, _mda_patterns(item.get("form") or ""))
        risk_text = _extract_section(text, _risk_patterns(item.get("form") or ""), min_len=3000, cap=150_000)
        payload = {
            "accession": item.get("accession"),
            "form": item.get("form"),
            "filed": item.get("date"),
            "period": item.get("report_date"),
            "url": item.get("url"),
            "index_url": item.get("index_url"),
            "title": item.get("description") or item.get("form"),
            "mda": _section_payload(mda_text, "MD&A") if mda_text else None,
            "risk": _section_payload(risk_text, "风险因素") if risk_text else None,
        }
        if not payload["mda"]:
            logger.info("no MD&A section found in %s", item.get("url"))
        return payload

    return await cache.get(key, 7 * 24 * 3600, factory)


async def _safe_analyze(item: dict[str, Any], warnings: list[str], label: str) -> dict[str, Any] | None:
    try:
        return await _analyze_filing(item)
    except Exception as exc:
        logger.warning("filing analysis failed for %s: %s", item.get("accession"), exc)
        warnings.append(f"{label} 文本解析失败")
        return None


def _theme_moves(current: dict[str, Any], prior: dict[str, Any]) -> list[dict[str, Any]]:
    current_map = {item["key"]: item for item in current.get("themes", [])}
    prior_map = {item["key"]: item for item in prior.get("themes", [])}
    moves = []
    for key in set(current_map) | set(prior_map):
        now = current_map.get(key, {}).get("per10k", 0.0)
        before = prior_map.get(key, {}).get("per10k", 0.0)
        delta = round(now - before, 2)
        if abs(delta) < 0.5:
            continue
        moves.append(
            {
                "key": key,
                "label": current_map.get(key, prior_map.get(key, {})).get("label", key),
                "delta": delta,
                "current": now,
                "prior": before,
            }
        )
    moves.sort(key=lambda item: -abs(item["delta"]))
    return moves[:5]


def _section_moves(current: dict[str, Any], prior: dict[str, Any]) -> list[dict[str, Any]]:
    current_map = {item["label"]: item for item in current.get("sections", [])}
    prior_map = {item["label"]: item for item in prior.get("sections", [])}
    moves = []
    for label in set(current_map) | set(prior_map):
        now = float(current_map.get(label, {}).get("share") or 0)
        before = float(prior_map.get(label, {}).get("share") or 0)
        if abs(now - before) < 0.8:
            continue
        moves.append({"label": label, "current": round(now, 1), "prior": round(before, 1), "delta": round(now - before, 1)})
    moves.sort(key=lambda item: -abs(item["delta"]))
    return moves[:5]


def _public_statement(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": item.get("role"),
        "role_label": item.get("role_label"),
        "tone": item.get("tone"),
        "topic": item.get("topic"),
        "text": item.get("text"),
        "section": item.get("section"),
    }


STOP_WORDS = frozenset(
    "a an and are as at be been but by for from had has have if in into is it its may of on or our "
    "that the their these this those to was were which will with would we us company".split()
)


def _statement_tokens(sentence: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", sentence.lower()) if token not in STOP_WORDS}


def _statement_similarity(left: str, right: str) -> float:
    a, b = _statement_tokens(left), _statement_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _statement_delta(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    current_hashes = set(current.get("_hashes") or [])
    prior_hashes = set(prior.get("_hashes") or [])
    prior_keys = list(prior.get("_key_sentences", []))
    matched_prior: set[str] = set()
    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    for item in current.get("_key_sentences", []):
        if item.get("hash") in prior_hashes:
            continue
        best, best_score = None, 0.0
        for previous in prior_keys:
            if previous.get("hash") in matched_prior:
                continue
            score = _statement_similarity(item.get("text", ""), previous.get("text", ""))
            if score > best_score:
                best, best_score = previous, score
        if best is not None and best_score >= 0.62:
            matched_prior.add(best.get("hash", ""))
            changed.append({
                "current": _public_statement(item),
                "prior": _public_statement(best),
                "similarity": round(best_score, 2),
            })
            continue
        added.append(_public_statement(item))
    removed = [
        _public_statement(item)
        for item in prior_keys
        if item.get("hash") not in current_hashes and item.get("hash") not in matched_prior
    ]
    overlap = len(current_hashes & prior_hashes) / len(prior_hashes) * 100 if prior_hashes else None
    return {
        "added": added[:4],
        "removed": removed[:3],
        "changed": changed[:3],
        "added_count": max(0, len(current_hashes) - len(current_hashes & prior_hashes)),
        "removed_count": max(0, len(prior_hashes) - len(current_hashes & prior_hashes)),
        "retained_pct": round(overlap, 1) if overlap is not None else None,
        "guidance_current": len(current.get("guidance") or []),
        "guidance_prior": len(prior.get("guidance") or []),
    }


def _delta_payload(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    return {
        "prior_filed": prior.get("filed"),
        "prior_form": prior.get("form"),
        "tone": round(current["tone"]["net"] - prior["tone"]["net"], 3),
        "negative": round(current["tone"]["negative"] - prior["tone"]["negative"], 2),
        "uncertainty": round(current["tone"]["uncertainty"] - prior["tone"]["uncertainty"], 2),
        "flesch": round(current["stats"]["flesch"] - prior["stats"]["flesch"], 1),
        "words": current["stats"]["words"] - prior["stats"]["words"],
        "theme_moves": _theme_moves(current, prior),
        "section_moves": _section_moves(current, prior),
        "statements": _statement_delta(current, prior),
    }


def _risk_delta(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    current_hashes = set(current.get("_hashes") or [])
    prior_hashes = set(prior.get("_hashes") or [])
    added = [
        _public_statement(item)
        for item in current.get("_key_sentences", [])
        if item.get("hash") not in prior_hashes
    ][:3]
    resolved = [
        _public_statement(item)
        for item in prior.get("_key_sentences", [])
        if item.get("hash") not in current_hashes
    ][:2]
    return {
        "theme_moves": _theme_moves(current, prior),
        "added": added,
        "resolved": resolved,
        "added_count": max(0, len(current_hashes) - len(current_hashes & prior_hashes)),
    }


def _strip_internal(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_internal(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [_strip_internal(item) for item in value]
    return value


def _quality_notes(current: dict[str, Any], delta: dict[str, Any] | None) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    if delta:
        if delta["tone"] >= 0.04:
            notes.append(
                {
                    "tone": "positive",
                    "text": f"MD&A 净语气较上一份年报改善 {delta['tone']:+.3f}，管理层表述更积极。",
                }
            )
        elif delta["tone"] <= -0.04:
            notes.append(
                {
                    "tone": "caution",
                    "text": f"MD&A 净语气较上一份年报走弱 {abs(delta['tone']):.3f}，措辞转向谨慎。",
                }
            )
        if delta["uncertainty"] >= 1.5:
            notes.append(
                {
                    "tone": "caution",
                    "text": f"不确定性措辞密度上升 {delta['uncertainty']:+.1f} 次/万词。",
                }
            )
        if delta["flesch"] <= -3:
            notes.append(
                {
                    "tone": "caution",
                    "text": f"Flesch 可读性下降 {abs(delta['flesch']):.1f} 分，文本更趋复杂。",
                }
            )
        if delta["words"] > 0.25 * max(1, current["stats"]["words"] - delta["words"]):
            notes.append(
                {
                    "tone": "neutral",
                    "text": f"较上一份年报扩写 {delta['words']:,} 词，披露范围明显扩大。",
                }
            )
        for move in delta["theme_moves"][:2]:
            if move["delta"] >= 1.0 and move["key"] in {"ai", "tariffs_trade", "cyber", "inflation_pricing", "china_geo"}:
                notes.append(
                    {
                        "tone": "neutral",
                        "text": f"「{move['label']}」提及密度上升 {move['delta']:.1f} 次/万词。",
                    }
                )
    if current["tone"]["negative"] > current["tone"]["positive"]:
        notes.append(
            {
                "tone": "caution",
                "text": f"负面措辞密度（{current['tone']['negative']:.1f}）高于正面（{current['tone']['positive']:.1f}），需结合风险因素阅读。",
            }
        )
    if not notes and delta:
        notes.append({"tone": "neutral", "text": "文本语气与主题结构较上一份年报变化有限。"})
    return notes[:5]


async def mda(symbol: str) -> dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    cik = await sec.cik_for(symbol)
    if not cik:
        return {
            "symbol": symbol,
            "available": False,
            "message": "SEC EDGAR 未收录该标的，MD&A 文本分析不适用。",
            "annual": None,
            "quarterly": None,
            "notes": [],
            "warnings": [],
            "source": "sec_edgar",
            "as_of": datetime.now(ET).isoformat(timespec="seconds"),
        }
    filings_payload = await sec.filings(symbol, limit=12, forms={"10-K", "10-Q", "20-F", "40-F"})
    items = filings_payload.get("items") or []
    annual_items = [item for item in items if (item.get("form") or "") in {"10-K", "20-F", "40-F"}]
    quarterly_items = [item for item in items if (item.get("form") or "") == "10-Q"]
    warnings: list[str] = []

    annual_item = annual_items[0] if annual_items else None
    prior_item = annual_items[1] if len(annual_items) > 1 else None
    quarterly_item = quarterly_items[0] if quarterly_items else None

    tasks = []
    if annual_item:
        tasks.append(_safe_analyze(annual_item, warnings, "年报"))
    if prior_item:
        tasks.append(_safe_analyze(prior_item, warnings, "上一份年报"))
    if quarterly_item:
        tasks.append(_safe_analyze(quarterly_item, warnings, "季报"))
    results = await asyncio.gather(*tasks) if tasks else []
    annual = deepcopy(results[0]) if annual_item and results[0] else None
    prior = deepcopy(results[1]) if annual_item and prior_item and len(results) > 1 and results[1] else None
    quarterly = deepcopy(results[-1]) if quarterly_item and results[-1] else None
    if not annual_item:
        quarterly = deepcopy(results[0]) if quarterly_item and results and results[0] else None

    if annual and annual.get("mda"):
        delta = _delta_payload(annual["mda"], prior["mda"]) if prior and prior.get("mda") else None
        if delta:
            delta["prior_filed"] = prior.get("filed")
            delta["prior_form"] = prior.get("form")
        annual["delta"] = delta
        annual["quality_notes"] = _quality_notes(annual["mda"], delta)
    if annual and prior and annual.get("risk") and prior.get("risk"):
        annual["risk_delta"] = _risk_delta(annual["risk"], prior["risk"])
    notes: list[dict[str, str]] = []
    if annual and not (prior and prior.get("mda")):
        notes.append(
            {
                "scope": "annual",
                "tone": "neutral",
                "text": "未找到可对比的上一份年报（高频发行人可能超出最近申报窗口），已跳过同比文本对比。",
            }
        )
    if not annual and quarterly:
        notes.append(
            {
                "scope": "quarterly",
                "tone": "neutral",
                "text": "未找到 10-K/20-F 年报，仅展示最新 10-Q 的 MD&A。",
            }
        )
    return {
        "symbol": symbol,
        "cik": cik,
        "company": filings_payload.get("company"),
        "available": bool((annual or {}).get("mda") or (quarterly or {}).get("mda")),
        "annual": _strip_internal(annual),
        "quarterly": _strip_internal(quarterly),
        "notes": notes,
        "warnings": warnings,
        "source": "sec_edgar",
        "as_of": datetime.now(ET).isoformat(timespec="seconds"),
    }
