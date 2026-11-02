"""共同基金 / ETF 研究：SEC EDGAR 的 N-PORT 持仓与 497K 招募说明书摘要。

免密钥且只用公开申报：ticker→CIK 走 browse-edgar atom，持仓走 NPORT-P 原始
XML，费率与目标走 497K 摘要说明书。N-PORT 为季度数据，缓存以天为单位。
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections import defaultdict
from typing import Any
from xml.etree import ElementTree as ET

from server.config import CACHE_DIR, SEC_HEADERS
from server.data import analysis, nasdaq
from server.data.cache import JsonCache
from server.data.http import UpstreamError, http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)


class FundNotFound(RuntimeError):
    """份额代码在 EDGAR 与 Nasdaq 都查无档案，属于用户输入问题而非上游故障。"""

ATOM_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={ticker}&type=NPORT-P&output=atom"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
XSL_PREFIX = re.compile(r"^[^/]*xsl[^/]*/", re.IGNORECASE)
TAG_STRIP = re.compile(r"<[^>]+>")
SPACE_STRIP = re.compile(r"\s+")
NAME_NOISE = re.compile(r"[^A-Z0-9 ]+")
NAME_SUFFIXES = {
    "INC", "LLC", "LTD", "CORP", "CORPORATION", "CO", "COMPANY", "PLC", "SA", "NV", "AG",
    "GMBH", "HOLDING", "HOLDINGS", "THE", "GROUP", "GP", "LP", "TR", "TRUST", "PARTNERS",
    "PARTNERSHIP", "SP", "ADR", "ADS", "NEW", "SHARES", "SHARE", "STOCK", "CDAK", "SE",
}
ASSET_CATEGORIES = {
    "EC": "普通股",
    "PA": "优先股",
    "MM": "货币市场工具",
    "OTH": "其他股权",
    "CLI": "封闭式基金",
    "OIC": "开放式基金",
    "IF": "基础设施基金",
    "MF": "共同基金份额",
    "ETP": "交易所交易产品",
    "SERO": "其他证券",
    "DBT": "债券",
    "BDSW": "外币债券",
    "CD": "存单",
    "CP": "商业票据",
    "TB": "美国国债",
    "MBS": "抵押贷款支持证券",
    "ABS": "资产支持证券",
    "CORP": "公司债",
    "FF": "政府机构债",
    "FAC": "浮动利率贷款",
    "CB": "可转债",
    "PFD": "优先债",
    "CASH": "现金/等价物",
    "OTHCM": "其他商品",
    "FIT": "房地产信托",
    "STIV": "短期投资工具",
    "EP": "优先股",
}
ISSUER_CATEGORIES = {
    "I9": "美国财政部",
    "RF": "美国政府机构",
    "US": "美国公司",
    "AF": "外国政府",
    "A10": "超主权/多边",
    "CORP": "外国公司",
    "FUND": "基金",
    "BLKCPN": "银行承兑",
    "CD": "存单发行人",
}
COUNTRIES = {
    "US": "美国", "CA": "加拿大", "GB": "英国", "JP": "日本", "DE": "德国", "FR": "法国",
    "HK": "中国香港", "CN": "中国", "TW": "中国台湾", "NL": "荷兰", "CH": "瑞士", "AU": "澳大利亚",
    "KY": "开曼群岛", "IE": "爱尔兰", "LU": "卢森堡", "SG": "新加坡", "KR": "韩国", "IN": "印度",
    "ES": "西班牙", "IT": "意大利", "BE": "比利时", "SE": "瑞典", "DK": "丹麦", "MX": "墨西哥",
    "BR": "巴西", "ZA": "南非", "MO": "中国澳门", "NZ": "新西兰", "NO": "挪威", "FI": "芬兰",
}
NPORT_FORMS = {"NPORT-P", "NPORT-1143"}
PROSPECTUS_FORMS = {"497K", "497", "N-CSRS", "N-CSR"}
HISTORY_DAYS = 1900
SEC_MIN_INTERVAL = 0.12
_throttle_lock = asyncio.Lock()
_next_slot = 0.0


async def _throttle() -> None:
    global _next_slot
    async with _throttle_lock:
        now = time.monotonic()
        if _next_slot > now:
            await asyncio.sleep(_next_slot - now)
        _next_slot = time.monotonic() + SEC_MIN_INTERVAL


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _find(node: ET.Element, name: str) -> ET.Element | None:
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _find_all(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node.iter() if _local(child.tag) == name]


def _value(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _num(value: Any) -> float | None:
    try:
        return float(re.sub(r"[,\s%]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _attr(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    for key, value in node.attrib.items():
        if _local(key) == name:
            return str(value).strip()
    return ""


def normalize_name(name: Any) -> str:
    text = SPACE_STRIP.sub(" ", str(name or "").upper())
    text = NAME_NOISE.sub(" ", text).strip()
    words = [word for word in text.split() if word not in NAME_SUFFIXES and len(word) > 1]
    return " ".join(words) or text


async def _ticker_names() -> dict[str, str]:
    """EDGAR 公司名 → 股票代码，用于把 N-PORT 持仓映射成可点击的美股代码。"""

    async def factory() -> dict[str, str]:
        payload = await http.get_json(TICKER_MAP_URL, headers=SEC_HEADERS, retries=1, timeout=45)
        candidates: dict[str, set[str]] = defaultdict(set)
        for item in (payload or {}).values() if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper()
            title = normalize_name(item.get("title"))
            if ticker and title and len(title) > 3:
                candidates[title].add(ticker)
        return {title: next(iter(tickers)) for title, tickers in candidates.items() if len(tickers) == 1}

    return await cache.get("fund:ticker-names:v2", 24 * 3600, factory)


def _map_holdings(holdings: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    securities: dict[str, set[str]] = defaultdict(set)
    for item in holdings:
        identity = item.get("cusip") or item.get("isin") or item.get("title") or ""
        securities[normalize_name(item["name"])].add(identity)
    result = []
    for item in holdings:
        symbol = item.get("symbol")
        name = normalize_name(item["name"])
        if not symbol and item.get("asset_cat") == "EC" and len(securities[name]) == 1:
            symbol = names.get(name)
        result.append({**item, "symbol": symbol})
    return result


async def resolve_fund(ticker: str) -> dict[str, Any]:
    query = ticker.strip().upper()

    async def factory() -> dict[str, Any]:
        await _throttle()
        text = await http.get_text(
            ATOM_URL.format(ticker=query), headers=SEC_HEADERS, retries=1, timeout=30
        )
        cik = re.search(r"<cik>\s*(\d{1,10})\s*</cik>", text)
        name = re.search(r"<conformed-name>\s*(.*?)\s*</conformed-name>", text, re.S)
        if not cik:
            raise UpstreamError(f"{query} 未在 EDGAR 基金名录中命中")
        return {
            "ticker": query,
            "cik": f"{int(cik.group(1)):010d}",
            "registrant": SPACE_STRIP.sub(" ", (name.group(1) if name else "")).strip(),
        }

    return await cache.get(f"fund:cik:v1:{query}", 30 * 24 * 3600, factory)


async def _filings(cik: str) -> dict[str, list[dict[str, Any]]]:
    async def factory() -> dict[str, list[dict[str, Any]]]:
        await _throttle()
        payload = await http.get_json(
            SUBMISSIONS_URL.format(cik=cik), headers=SEC_HEADERS, retries=1, timeout=45
        )
        recent = (((payload or {}).get("filings") or {}).get("recent") or {}) if isinstance(payload, dict) else {}
        forms = recent.get("form") or []
        buckets: dict[str, list[dict[str, Any]]] = {"nport": [], "prospectus": []}
        for index, form in enumerate(forms):
            document = str((recent.get("primaryDocument") or [""] * len(forms))[index] or "")
            if not document:
                continue
            row = {
                "form": form,
                "accession": str((recent.get("accessionNumber") or [""] * len(forms))[index] or ""),
                "date": str((recent.get("filingDate") or [""] * len(forms))[index] or ""),
                "report_date": str((recent.get("reportDate") or [""] * len(forms))[index] or ""),
                "document": XSL_PREFIX.sub("", document),
            }
            if form in NPORT_FORMS:
                buckets["nport"].append(row)
            elif form in PROSPECTUS_FORMS:
                buckets["prospectus"].append(row)
        return buckets

    return await cache.get(f"fund:filings:v1:{cik}", 12 * 3600, factory)


NAME_STOP = {
    "FUND", "FUNDS", "THE", "INDEX", "INDEXED", "MORNINGSTAR", "SHARES", "SHARE", "CLASS",
    "SERIES", "TRUST", "ETF", "ETFS", "PORTFOLIO", "ADVISOR", "ADVISERS", "COMMODITY",
    "SELECT", "ADMIRAL", "INSTON", "RETAIL", "SERVICE", "SHAREMENT", "LEITERA", "PREMIER",
}
NPORT_PROBE_LIMIT = 60
NPORT_EARLY_EXIT = 0.8
# 冷启动时要逐个读几十份文件头，串行等待会让首屏慢到十几秒；SEC 限速 10 req/s，8 路并发刚好贴着上限
HEAD_CHUNK = 8


def _name_tokens(value: Any) -> set[str]:
    words = NAME_NOISE.sub(" ", str(value or "").upper()).split()
    return {word for word in words if len(word) > 2 and word not in NAME_STOP and word not in NAME_SUFFIXES}


def _name_words(value: Any) -> set[str]:
    """打分之外的"多出词"计数用：保留 K6/A2 这类两位数的份额标记，才能区分主类与子类。"""

    words = NAME_NOISE.sub(" ", str(value or "").upper()).split()
    return {word for word in words if len(word) > 1 and word not in NAME_STOP and word not in NAME_SUFFIXES}


def _name_score(left: Any, right: Any) -> float:
    """名称包含度：容忍 Nasdaq 展示名与 EDGAR seriesName 的后缀、插入词差异。"""

    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b:
        return 0.0
    hits = sum(
        1
        for word in a
        if any(
            word == other
            or (len(word) > 4 and len(other) > 4 and (word.startswith(other) or other.startswith(word)))
            for other in b
        )
    )
    # 分母取较大的一侧，避免 "VANGUARD" 这类单字词把无关 series 也判成满分
    return round(hits / max(len(a), len(b)), 3)


def _head_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>([^<]{{1,160}})<", text)
    return _plain(match.group(1)) if match else ""


async def _nport_header(cik: str, row: dict[str, Any]) -> dict[str, Any]:
    """只读取 N-PORT 首个数据块：身份信息都在文件开头，无需拉完几十 MB 持仓。"""

    async def factory() -> dict[str, Any]:
        url = ARCHIVE_URL.format(
            cik=int(cik), accession=row["accession"].replace("-", ""), document=row["document"]
        )
        await _throttle()
        raw = await http.get_prefix(url, headers=SEC_HEADERS, limit=16384, timeout=20)
        text = raw.decode("utf-8", errors="replace")
        return {
            "reg": _head_tag(text, "regName"),
            "series": _head_tag(text, "seriesName"),
            "period_end": _head_tag(text, "repPdDate"),
        }

    return await cache.get(f"fund:head:v1:{row['accession']}", 30 * 24 * 3600, factory)


def _nport_identity(hint: str, head: dict[str, Any]) -> float:
    """只按 seriesName 打分：同一注册人旗下所有候选的 regName 都相同，
    把它算进分会让无关 series 也拿到满分，从而挑错基金。"""

    series = head.get("series") or ""
    if not series:
        return _name_score(hint, head.get("reg")) * 0.6
    return _name_score(hint, series)


async def _rank_nport(cik: str, rows: list[dict[str, Any]], hint: str) -> list[tuple[dict[str, Any], float]]:
    """信托旗下每个 series 同日各交一份 N-PORT，逐个读文件头挑出正确的那份。"""

    if not rows:
        return []
    if not hint or len(rows) < 2:
        return [(rows[0], 1.0 if hint else 0.0)]
    scored: list[tuple[float, int, int, dict[str, Any]]] = []
    hint_tokens = _name_words(hint)
    indexed = list(enumerate(rows[:NPORT_PROBE_LIMIT]))
    for start in range(0, len(indexed), HEAD_CHUNK):
        chunk = indexed[start : start + HEAD_CHUNK]
        heads = await asyncio.gather(
            *(_nport_header(cik, row) for _index, row in chunk), return_exceptions=True
        )
        for (index, row), head in zip(chunk, heads):
            if isinstance(head, BaseException):
                logger.debug("N-PORT header failed for %s: %s", row["accession"], head)
                scored.append((0.0, 99, index, row))
                continue
            # 同名 series 常按份额类别再拆分（"… K6"、"… Admiral"），打分相同时取多出词最少的主类
            surplus = len(_name_words(head.get("series")) - hint_tokens)
            scored.append((_nport_identity(hint, head), surplus, index, row))
        if any(score >= NPORT_EARLY_EXIT for score, _extra, _index, _row in scored):
            break
    ranked = sorted(scored, key=lambda item: (-item[0], item[1], item[2]))
    tail = [
        (0.0, 99, index, row)
        for index, row in enumerate(rows[NPORT_PROBE_LIMIT:], start=NPORT_PROBE_LIMIT)
    ]
    return [(_row, score) for score, _extra, _index, _row in ranked + tail[:6]]


def _parse_nport(raw: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise UpstreamError(f"N-PORT XML 解析失败: {exc}") from exc

    holdings = []
    for item in _find_all(root, "invstOrSec"):
        name = _value(_find(item, "name"))
        value = _num(_value(_find(item, "valUSD")))
        if not name or value is None:
            continue
        identifiers = _find(item, "identifiers")
        symbol = _attr(_find(identifiers, "ticker"), "value").upper() if identifiers is not None else ""
        isin = _attr(_find(identifiers, "isin"), "value") if identifiers is not None else ""
        holdings.append(
            {
                "name": name,
                "title": _value(_find(item, "title")),
                "cusip": _value(_find(item, "cusip")),
                "isin": isin,
                "symbol": symbol if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol) else None,
                "value": value,
                "weight": _num(_value(_find(item, "pctVal"))) or 0.0,
                "balance": _num(_value(_find(item, "balance"))),
                "units": _value(_find(item, "units")),
                "currency": _value(_find(item, "curCd")),
                "asset_cat": _value(_find(item, "assetCat")),
                "issuer_cat": _value(_find(item, "issuerCat")),
                "country": _value(_find(item, "invCountry")),
                "fair_value_level": _value(_find(item, "fairValLevel")),
                "payoff": _value(_find(item, "payoffProfile")),
            }
        )
    holdings.sort(key=lambda item: item["value"], reverse=True)

    returns: list[dict[str, Any]] = []
    for row in _find_all(root, "monthlyTotReturn"):
        values = [_num(_attr(row, f"rtn{index}")) for index in (1, 2, 3)]
        if any(value is not None for value in values):
            returns.append({"class_id": _attr(row, "classId"), "returns": values})
    # 一份 N-PORT 会为多个份额类别各报一行，只保留主类别，避免把同一季度重复计入
    class_count = len(returns)
    primary_class = returns[0] if returns else None
    returns = returns[:1]

    flows: list[dict[str, Any]] = []
    for index in (1, 2, 3):
        node = _find(root, f"mon{index}Flow")
        if node is None:
            continue
        sales = _num(_attr(node, "sales"))
        redemption = _num(_attr(node, "redemption"))
        flows.append(
            {
                "month": index,
                "sales": sales,
                "redemption": redemption,
                "reinvestment": _num(_attr(node, "reinvestment")),
                "net_flow": sales - redemption if sales is not None and redemption is not None else None,
            }
        )

    return {
        "fund_name": _value(_find(root, "regName")),
        "series_name": _value(_find(root, "seriesName")),
        "period_end": _value(_find(root, "repPdDate")),
        "total_assets": _num(_value(_find(root, "totAssets"))),
        "net_assets": _num(_value(_find(root, "netAssets"))),
        "pct_float": _num(_value(_find(root, "pctFloatAssets"))),
        "cash_not_reported": _num(_value(_find(root, "cshNotRptdInCorD"))),
        "holdings": holdings,
        "monthly_returns": returns,
        "share_classes": class_count,
        "primary_class": (primary_class or {}).get("class_id"),
        "flows": flows,
    }


async def _nport_report(cik: str, filings: list[dict[str, Any]], hint: str = "") -> dict[str, Any]:
    """按名称匹配排序后逐个解析，直到拿到有持仓的 N-PORT 文件。"""

    ranked = await _rank_nport(cik, filings, hint)
    key = f"fund:nport:v3:{cik}:{ranked[0][0]['accession'] if ranked else 'none'}"

    async def factory() -> dict[str, Any]:
        errors: list[str] = []
        for row, score in ranked[:6]:
            url = ARCHIVE_URL.format(
                cik=int(cik), accession=row["accession"].replace("-", ""), document=row["document"]
            )
            try:
                await _throttle()
                raw = await http.get_bytes(url, headers=SEC_HEADERS, retries=1, timeout=60)
                report = _parse_nport(raw.decode("utf-8", errors="replace"))
            except Exception as exc:
                errors.append(f"{row['accession']}: {exc}")
                continue
            if report["holdings"] or report["net_assets"]:
                report["filing"] = {k: row.get(k) for k in ("accession", "date", "form", "report_date")}
                report["name_score"] = score
                return report
        raise UpstreamError(f"N-PORT 持仓不可用 ({'; '.join(errors[:2])})")

    return await cache.get(key, 30 * 24 * 3600, factory)


PCT = r"(-?\s?\d{1,5}(?:\.\d+)?)\s*%"


def _plain(value: str) -> str:
    return SPACE_STRIP.sub(" ", str(value).replace("®", "").replace("™", "")).strip(" .,;:")


CLASS_TICKER = re.compile(r"\b([A-Z]{4}[XK])\b")
# 5 位且以 X/K 结尾是零售基金份额代码的惯例，但要排除恰好同形的普通词
CLASS_DENIED = {"STOCK", "INDEX", "TRACK", "BREAK", "CHECK", "CLOCK", "WALKS", "TALKS", "POKER"}
LABEL_PATTERNS = (
    r"(?:Fund|Class)\s*/\s*Ticker\s+(.{3,140}?)\s*/\s*([A-Z]{4}[XK])\b",
    r"Summary Prospectus\s*[|]?\s*(?:[A-Z][a-z]+ \d{1,2},? \d{4}\s+)?(.{6,110}?)\s+Ticker\s*[Ss]ymbol:?\s*[A-Z]{4}[XK]",
    r"Fund Summary Fund:\s+(.{3,140}?)\s+Investment Objective",
)
FEE_ROWS = {
    "management_fee": r"Management [Ff]ee[s]?",
    "distribution_fee": r"(?:[Dd]istribution (?:and/or Service )?\(?12b-1\)? ?[Ff]ee[s]?|12b-1[^%]{0,22}[Ff]ee[s]?)",
    "other_expenses": r"Other [Ee]xpenses?",
    "total_expenses": r"Total annual(?: fund)? operating expenses",
    "net_expenses": r"Total annual(?: fund)? operating expenses[^0-9]{0,60}after expense reduction",
}
# 业绩基准的措辞各家不同：优先取 "(reflects no deduction …)" 那一行，其余按常见句式兜底
BENCHMARK_PATTERNS = (
    r"[Bb]enchmarked to (?:the )?([A-Z][A-Za-z0-9&.'\- ]{3,70})",
    r"[Ii]ndex [Bb]enchmark\s+([A-Z][A-Za-z0-9&.'\- ]{3,70})",
    r"(?:compared (?:with|to)|against) (?:the )?([A-Z][A-Za-z0-9&.'\- ]{3,70}? Index)",
    r"([A-Z][A-Za-z0-9&.'\- ]{3,70}?(?: Index|Benchmark Index))",
)


def _class_codes(text: str, limit: int = 3000) -> list[str]:
    codes: list[str] = []
    for code in CLASS_TICKER.findall(text[:limit]):
        if code in CLASS_DENIED or code in codes:
            continue
        codes.append(code)
    return codes


def _class_section(text: str, ticker: str) -> str:
    """Fidelity 会把几个份额类别的摘要说明书拼成一份 497K（每类一张费用表）。
    按类别代码首次出现的位置切出本类别那一段，费率/经理/年度回报才不会串行。"""

    positions: list[tuple[int, str]] = []
    for match in CLASS_TICKER.finditer(text):
        code = match.group(1)
        if code in CLASS_DENIED or any(code == item[1] for item in positions):
            continue
        positions.append((match.start(), code))
    if len(positions) < 2:
        return text
    target = next((pos for pos, code in positions if code == ticker), None)
    if target is None:
        return text
    nxt = [pos for pos, _code in positions if pos > target]
    return text[target : nxt[0] if nxt else len(text)]


def _prospectus_label(text: str) -> str:
    for pattern in LABEL_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            return _plain(match.group(1))
    return ""


def _fee_row_hits(text: str, pattern: str) -> list[re.Match]:
    """费率行必须紧跟数值（或 None/N/A），正文里讨论管理费的句子不该被当成表格行。"""

    hits = []
    for item in re.finditer(pattern, text, re.I):
        tail = text[item.end() : item.end() + 90]
        if re.match(r"\s*(?:\([^)]{0,80}\))?\s*(?:None|N/A|—|–|-|\d)", tail, re.I):
            hits.append(item)
    return hits


def _fee_value(text: str, pattern: str, column: int) -> float | None:
    """费率按份额类别所在列取值：Vanguard 并排印多列，Schwab/Fidelity 只有一列。"""

    hits = _fee_row_hits(text, pattern)
    if not hits:
        return None
    tail = text[hits[0].end() : hits[0].end() + 90]
    if re.match(r"\s*(?:None|N/A|—|–)", tail, re.I):
        return None
    tail = re.sub(r"\([^)]{0,4}\d{1,2}\)", " ", tail)
    marks = [item for item in re.findall(r"-?\d{1,4}(?:\.\d+)?\s*%?", tail) if "." in item or "%" in item]
    if not marks:
        return None
    return _num(marks[min(column, len(marks) - 1)])


def _class_window(text: str, column: int) -> tuple[str, int]:
    """一份 497K 里并排多个份额类别时（Fidelity 常见），把解析范围缩到目标类别那一段，
    否则目标/经理/年度回报会全部串到第一个类别上。"""

    hits = _fee_row_hits(text, FEE_ROWS["management_fee"])
    if column <= 0 or len(hits) < 2:
        return text, column
    index = min(column, len(hits) - 1)
    start = max(0, hits[index].start() - 900)
    end = hits[index + 1].start() - 900 if index + 1 < len(hits) else len(text)
    return text[start : max(start + 200, end)], 0


BENCHMARK_NAMED = re.compile(
    r"((?:S&amp;P|S&P|MSCI|CRSP|Russell|Bloomberg|Nasdaq|NASDAQ|Dow[ ]Jones|FTSE|Morningstar|Barclays|"
    r"Morgan[ ]Stanley|CBOE|ICE|Refinitiv|Lucien)[^().%]{0,55}?(?:Index|Benchmark|Composite|TR)\b)",
    re.I,
)


def _benchmark_name(block: str, pos: int) -> str:
    """基准行通常写作 "CRSP US Total Market Index (reflects no deduction …)"，
    只认知名指数前缀，避免把表头里的 "Comparative Index" 当成基准。"""

    named = None
    for item in BENCHMARK_NAMED.finditer(block[:pos]):
        named = item.group(1)
    return _plain(named) if named else ""


def _adviser_block(text: str) -> str:
    """"Investment Adviser/Advisor + 机构名" 才是栏目抬头，正文里也反复出现这个词组；
    取最后一处后面紧跟大写词的，顾问栏通常印在文件末尾。"""

    hits = [item for item in re.finditer(r"Investment Advis(?:er|or)\s+(?=[A-Z])", text)]
    if not hits:
        return ""
    item = hits[-1]
    return text[item.end() : item.end() + 300]


def _adviser_name(value: str) -> str:
    """正文里 "investment adviser" 也出现在普通句子中，只取确实像机构名的那段。"""

    text = _plain(value)
    short = re.search(r"([A-Z][A-Z&.]{1,8}) \(the Adviser\)", text)
    if short:
        return short.group(1)
    match = re.search(
        r"([A-Z][A-Za-z&.,'’\- ]{3,70}?(?:Inc|LLC|L\.P|Asset Management"
        r"|Management(?: & Research)? Company|Advisers|Capital Management|Investors|Trust|Research))",
        text,
    )
    return match.group(1).strip(" ,.") if match else ""


def _parse_prospectus(raw: str, ticker: str = "", column: int = 0) -> dict[str, Any]:
    """从 497K 摘要说明书抽取费率、目标、经理与年度回报，基金页直接可用。"""

    text = SPACE_STRIP.sub(" ", html.unescape(TAG_STRIP.sub(" ", raw)))
    # 多个类别各印一张费用表时（Fidelity 常见），把正文缩到目标类别那一段再解析
    if len(_fee_row_hits(text, FEE_ROWS["management_fee"])) > 1:
        full_codes = _class_codes(text, len(text))
        if ticker in full_codes:
            text, column = _class_window(text, full_codes.index(ticker))

    def grab(pattern: str) -> str:
        match = re.search(pattern, text, re.I)
        return match.group(1).strip() if match else ""

    def locate(needles: str | tuple[str, ...], from_index: int = 0) -> tuple[int, int]:
        """同一栏目各家的措辞不同（Vanguard 写 Average Annual Total Returns），
        取最先命中的锚点，大小写不敏感。"""

        items = (needles,) if isinstance(needles, str) else tuple(needles)
        best = (-1, -1)
        for item in items:
            match = re.search(re.escape(item), text[from_index:], re.I)
            if match and (best[0] < 0 or from_index + match.start() < best[0]):
                best = (from_index + match.start(), from_index + match.end())
        return best

    def between(start: str | tuple[str, ...], stop: str | tuple[str, ...], limit: int = 900) -> str:
        head_start, head_end = locate(start)
        if head_start < 0:
            return ""
        tail_start, _ = locate(stop, head_end)
        return text[head_end : tail_start if tail_start > head_end else len(text)].strip()[:limit]

    def excerpt(start: str | tuple[str, ...], stop: str | tuple[str, ...], limit: int) -> str:
        segment = between(start, stop, limit + 1)
        if len(segment) <= limit:
            return segment
        return segment[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"

    def marks(segment: str) -> list[float | None]:
        return [_num(item) for item in re.findall(PCT, segment)]

    codes = _class_codes(text)
    turnover = grab(r"portfolio turnover rate was\s*([0-9.]+)\s*%")
    fund_label = _prospectus_label(text)

    annual_block = between(
        ("Year-by-Year Returns", "Calendar Years", "Annual Total Returns"),
        ("Average Annual", "Investment Adviser", "During the periods shown"),
        700,
    )
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", annual_block)
    values = marks(annual_block[annual_block.rfind(years[-1]) + 4 :])[-len(years) :] if years else []
    annual_returns = [
        {"year": int(year), "return": value}
        for year, value in zip(years[len(years) - len(values) :], values)
        if value is not None
    ]

    avg_block = _plain(
        between(
            ("Average Annual Total Returns", "Average Annual Returns"),
            ("Investment Adviser", "Portfolio Manager", "Purchase and Sale", "More Trust Information"),
            1200,
        )
    )
    periods = [int(item) for item in re.findall(r"(?:Past\s+)?(\d{1,2})\s+(?:[Yy]ears?)", avg_block)][:3]

    def row_values(pattern: str) -> list[float | None]:
        match = re.search(pattern, avg_block, re.I)
        return marks(avg_block[match.start() : match.start() + 240])[:3] if match else []

    benchmark_match = re.search(r"\(reflects no deduction", avg_block, re.I)
    benchmark = _benchmark_name(avg_block, benchmark_match.start()) if benchmark_match else ""
    if not benchmark:
        named = BENCHMARK_NAMED.search(avg_block) or BENCHMARK_NAMED.search(text)
        benchmark = _plain(named.group(1)) if named else ""
    if not benchmark:
        for pattern in BENCHMARK_PATTERNS:
            fallback = re.search(pattern, avg_block or text, re.I)
            if fallback:
                benchmark = _plain(fallback.group(1))
                break
    managers = [
        {"name": _plain(item.group(1)), "role": _plain(item.group(2)), "since": item.group(3)}
        for item in re.finditer(
            r"([A-Z][A-Za-z'’\- ]{3,40}?)\s*\(([^)]{2,45})\)\s*(?:has|have)[^.;]{0,90}?(?:managed|worked with)[^.;]*since\s+"
            r"(?:[A-Z][a-z]+ \d{1,2}, )?(\d{4})",
            between("Portfolio Manager(s)", ("Purchase and Sale of Shares", "Questions", "More Trust Information"), 900),
        )
    ]
    quarter: dict[str, Any] = {}
    for key, label in (("best", "Highest"), ("worst", "Lowest")):
        match = re.search(
            rf"{label}(?:\s+(?:Quarter|Calendar Quarter)\s+Return)?\s+{PCT}\s+([A-Z][a-z]+ \d{{1,2}}, \d{{4}})", text
        )
        if match:
            quarter[key] = {"return": _num(match.group(1)), "date": match.group(2)}
    # Schwab 写作 "Best Quarter: 20.55% Q2 2020"，且用括号表示负收益
    if not quarter:
        for key, label in (("best", "Best"), ("worst", "Worst")):
            match = re.search(
                rf"{label}[^A-Za-z0-9]{{0,12}}Quarter:?\s*(\()?\s*{PCT}\s*\)?\s*Q([1-4])\s+(\d{{4}})", text, re.I
            )
            if match:
                value = _num(match.group(2))
                if value is not None:
                    quarter[key] = {
                        "return": -value if match.group(1) else value,
                        "date": f"Q{match.group(3)} {match.group(4)}",
                    }
    cost_block = between(
        (
            "For every $10,000 you invested",
            "Expenses on a $10,000 Investment",
            "This example is intended",
            "Projected Annual Fees",
            "The following examples",
            "The following example",
            "Illustrative Examples",
        ),
        ("Portfolio Turnover", "Questions", "Why might the return", "Additional Information"),
        640,
    )
    cost: dict[str, float | None] = {}
    # Vanguard/Schwab 先排期限再排金额（"1 Year 3 Years 5 Years 10 Years $4 $13 $23 $51"），
    # 紧跟的 $ 是必需的：业绩表里同样有 "1 Year 5 Years"，但后面跟的是百分比。
    header = re.search(r"((?:\d{1,2}\s+[Yy]ears?\s+){2,4})\s*\$([\d,]+)", cost_block)
    if header:
        spans = [int(item) for item in re.findall(r"(\d{1,2})\s+[Yy]ears?", header.group(1))]
        amounts = [_num(item) for item in re.findall(r"\$\s*([\d,]+)", cost_block[header.end(1) : header.end(1) + 140])]
        cost = {f"{span}y": amount for span, amount in zip(spans, amounts) if amount is not None}
    if not cost:
        cost = {
            f"{item.group(1)}y": _num(item.group(2))
            for item in re.finditer(r"(\d{1,2})\s+years?\s+\$\s*([\d,]+)", cost_block, re.I)
        }

    return {
        "class_ticker": ticker or (codes[0] if codes else ""),
        "class_tickers": codes,
        "fund_label": fund_label,
        "management_fee": _fee_value(text, FEE_ROWS["management_fee"], column),
        "distribution_fee": _fee_value(text, FEE_ROWS["distribution_fee"], column),
        "other_expenses": _fee_value(text, FEE_ROWS["other_expenses"], column),
        "total_expenses": _fee_value(text, FEE_ROWS["total_expenses"], column),
        "net_expenses": _fee_value(text, FEE_ROWS["net_expenses"], column),
        "portfolio_turnover": _num(turnover),
        "objective": _plain(excerpt("Investment Objective", ("Fee Table", "Fees and Expenses", "Important"), 240)),
        "strategies": _plain(excerpt("Principal Investment Strategies", "Principal Investment Risks", 700)),
        "benchmark": re.sub(r"^A\s+", "", benchmark),
        "adviser": _adviser_name(_adviser_block(text)),
        "managers": managers[:6],
        "annual_returns": annual_returns,
        "average_returns": {
            "periods": periods,
            "fund": row_values(r"Return Before Taxes|Before Taxes"),
            "benchmark": row_values(r"\(reflects no deduction"),
        },
        "quarter_extremes": quarter,
        "cost_example": cost,
        "text_length": len(text),
    }


async def _prospectus_head(cik: str, row: dict[str, Any]) -> dict[str, Any]:
    """只读摘要说明书开头几百字节，确认这份 497K 覆盖哪些份额代码。"""

    async def factory() -> dict[str, Any]:
        url = ARCHIVE_URL.format(
            cik=int(cik), accession=row["accession"].replace("-", ""), document=row["document"]
        )
        await _throttle()
        raw = await http.get_prefix(url, headers=SEC_HEADERS, limit=8192, timeout=20)
        text = SPACE_STRIP.sub(
            " ", html.unescape(TAG_STRIP.sub(" ", raw.decode("utf-8", errors="replace")))
        )
        return {"tickers": _class_codes(text), "label": _prospectus_label(text)}

    return await cache.get(f"fund:proshead:v2:{row['accession']}", 30 * 24 * 3600, factory)


async def _prospectus(cik: str, filings: list[dict[str, Any]], ticker: str, hint: str = "") -> dict[str, Any]:
    key = f"fund:prospectus:v16:{cik}:{ticker}"

    async def factory() -> dict[str, Any]:
        # 信托旗下每只基金各有一份 497K；先扫文件头找到份额代码命中的那份，再完整解析
        order = [row for row in filings if row["form"] == "497K"]
        order += [row for row in filings if row["form"] != "497K"]
        queue = list(enumerate(order[:40]))
        chosen: tuple[dict[str, Any], int] | None = None
        fallback: tuple[dict[str, Any], int] | None = None
        for start in range(0, len(queue), HEAD_CHUNK):
            chunk = queue[start : start + HEAD_CHUNK]
            heads = await asyncio.gather(
                *(_prospectus_head(cik, row) for _index, row in chunk), return_exceptions=True
            )
            for (_index, row), head in zip(chunk, heads):
                if isinstance(head, BaseException):
                    logger.debug("prospectus head failed for %s: %s", row["accession"], head)
                    continue
                if ticker in head["tickers"]:
                    chosen = (row, head["tickers"].index(ticker))
                    break
                if fallback is None and _name_score(hint, head["label"]) >= 0.6:
                    fallback = (row, 0)
            if chosen is not None:
                break
        chosen = chosen or fallback
        if chosen is None:
            return {}
        row, column = chosen
        url = ARCHIVE_URL.format(
            cik=int(cik), accession=row["accession"].replace("-", ""), document=row["document"]
        )
        try:
            await _throttle()
            raw = await http.get_bytes(url, headers=SEC_HEADERS, retries=1, timeout=30)
            parsed = _parse_prospectus(raw.decode("utf-8", errors="replace"), ticker, column)
        except Exception as exc:
            logger.warning("prospectus parse failed for %s: %s", url, exc)
            return {}
        if parsed.get("total_expenses") is None and parsed.get("management_fee") is None:
            return {}
        parsed["form"] = row["form"]
        parsed["filed"] = row["date"]
        return parsed

    return await cache.get(key, 30 * 24 * 3600, factory)


def _concentration(
    holdings: list[dict[str, Any]], net_assets: float | None, *, partial: bool = False
) -> dict[str, Any]:
    weights = [max(item["weight"], 0.0) for item in holdings]
    total = sum(weights)
    top10 = sum(sorted(weights, reverse=True)[:10])
    top20 = sum(sorted(weights, reverse=True)[:20])
    hhi = sum((weight / (total or 1)) ** 2 for weight in weights) * 10000
    buckets: dict[str, float] = defaultdict(float)
    countries: dict[str, float] = defaultdict(float)
    issuers: dict[str, float] = defaultdict(float)
    for item in holdings:
        buckets[ASSET_CATEGORIES.get(item["asset_cat"], item["asset_cat"] or "其他")] += item["weight"]
        countries[COUNTRIES.get(item["country"], item["country"] or "未披露")] += item["weight"]
        if item["issuer_cat"]:
            issuers[ISSUER_CATEGORIES.get(item["issuer_cat"], item["issuer_cat"])] += item["weight"]

    def ranked(source: dict[str, float], limit: int = 8) -> list[dict[str, Any]]:
        rows = [{"label": key, "weight": round(value, 2)} for key, value in source.items() if value >= 0.05]
        rows.sort(key=lambda item: item["weight"], reverse=True)
        return rows[:limit]

    return {
        "positions": len(holdings),
        "basis": "disclosed_top10" if partial else "nport_full",
        "reported_weight": round(total, 1),
        "top10": round(top10, 1),
        "top20": round(top20, 1),
        "hhi": None if partial else round(hhi, 1),
        "effective_positions": None if partial else (round(10000 / hhi, 1) if hhi else None),
        "asset_mix": [] if partial else ranked(buckets),
        "country_mix": [] if partial else ranked(countries, 6),
        "issuer_mix": [] if partial else ranked(issuers, 6),
        "coverage": round(sum(item["value"] or 0 for item in holdings) / net_assets * 100, 1)
        if net_assets
        else None,
    }


async def _safe(coro: Any, label: str, default: Any) -> Any:
    try:
        return await coro
    except Exception as exc:
        logger.info("fund %s unavailable: %s", label, exc)
        return default


def _clean_nav(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剔除净值序列里的单日坏点（前后邻点一致、中间跳变数倍），份额折算的持续台阶会保留。"""

    result: list[dict[str, Any]] = []
    for index, bar in enumerate(bars):
        value = _num(bar.get("c"))
        if 0 < index < len(bars) - 1 and value:
            prev = _num(bars[index - 1].get("c"))
            nxt = _num(bars[index + 1].get("c"))
            if prev and nxt and abs(prev / nxt - 1) < 0.1:
                anchor = (prev + nxt) / 2
                if value / anchor > 1.8 or value / anchor < 0.55:
                    continue
        result.append(bar)
    return result


async def _profile(ticker: str) -> dict[str, Any]:
    meta = await _safe(nasdaq.fund_meta(ticker), "profile", {})
    bars = await _safe(nasdaq.fund_history(ticker, HISTORY_DAYS), "history", []) if meta else []
    return {"meta": meta or {}, "bars": _clean_nav(bars or [])}


def _return_series(bars: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    adjusted = bool(bars) and all((_num(bar.get("a")) or 0) > 0 for bar in bars)
    key = "a" if adjusted else "c"
    return [{"t": bar["t"], "c": bar[key]} for bar in bars], "adjusted" if adjusted else "price"


def _period_returns(bars: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [
        (str(bar.get("t")), float(bar["c"]))
        for bar in bars or []
        if _num(bar.get("c")) not in (None, 0)
    ]
    if not closes:
        return {}
    last = closes[-1][1]
    result: dict[str, Any] = {"as_of": closes[-1][0]}
    for label, count in (("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252), ("3y", 756), ("5y", 1260)):
        if len(closes) > count:
            result[label] = round((last / closes[-1 - count][1] - 1) * 100, 2)
    year = closes[-1][0][:4]
    start = next((price for date, price in reversed(closes) if date[:4] < year), None)
    if start:
        result["ytd"] = round((last / start - 1) * 100, 2)
    return result


async def fund_report(ticker: str, *, watch: list[str] | None = None) -> dict[str, Any]:
    """基金档案 + 净值分析 + N-PORT 持仓集中度 + 与自选的重叠，一次请求返回。"""

    query = (ticker or "").strip().upper()
    # Nasdaq 档案与 EDGAR 身份互不依赖，并发取回能省下一整段往返
    profile, meta = await asyncio.gather(
        _profile(query), _safe(resolve_fund(query), "edgar identity", None)
    )
    if not meta and not profile["meta"]:
        raise FundNotFound(f"{query} 无公开的基金档案")

    filings = {"nport": [], "prospectus": []}
    if meta:
        filings = await _safe(_filings(meta["cik"]), "filings", filings)

    hint = profile["meta"].get("name") or (meta or {}).get("registrant") or ""
    report: dict[str, Any] = {"holdings": [], "net_assets": None}
    prospectus: dict[str, Any] = {}
    if filings["nport"]:
        report, prospectus = await asyncio.gather(
            _nport_report(meta["cik"], filings["nport"], hint or ""),
            _prospectus(meta["cik"], filings["prospectus"], query, hint or ""),
            return_exceptions=True,
        )
        if isinstance(report, BaseException):
            logger.warning("fund holdings unavailable for %s: %s", query, report)
            report = {"holdings": [], "net_assets": None}
        if isinstance(prospectus, BaseException):
            logger.warning("fund prospectus unavailable for %s: %s", query, prospectus)
            prospectus = {}

    holdings = report.get("holdings") or []
    if not holdings:
        rows = await _safe(nasdaq.etf_holdings(query), "etf holdings", [])
        holdings = [
            {"name": row["name"] or row["symbol"], "symbol": row["symbol"], "weight": row["weight"] or 0.0,
             "value": None, "country": "", "asset_cat": "", "issuer_cat": ""}
            for row in rows
            if row.get("weight") is not None
        ]
    else:
        names = await _safe(_ticker_names(), "ticker mapping", {})
        holdings = _map_holdings(holdings, names)

    watch_set = {str(item).upper() for item in (watch or [])}
    overlap_by_symbol: dict[str, dict[str, Any]] = {}
    for item in holdings:
        symbol = item.get("symbol")
        if symbol in watch_set:
            entry = overlap_by_symbol.setdefault(symbol, {"symbol": symbol, "weight": 0.0, "name": item["name"]})
            entry["weight"] += item["weight"]
    overlap = sorted(
        [{**item, "weight": round(item["weight"], 2)} for item in overlap_by_symbol.values()],
        key=lambda item: item["weight"], reverse=True,
    )

    analytics = _concentration(holdings, report.get("net_assets"), partial=not report.get("holdings"))
    returns = [
        round(value, 2)
        for row in (report.get("monthly_returns") or [])
        for value in row["returns"]
        if value is not None
    ]
    compounded = 1.0
    for value in returns:
        compounded *= 1 + value / 100
    benchmark = await _safe(nasdaq.historical_etf("SPY", HISTORY_DAYS), "benchmark", [])
    series, basis = _return_series(profile["bars"])
    bench_series, bench_basis = _return_series(benchmark)
    comparable = bool(series and bench_series) and basis == bench_basis
    risk = analysis.risk_report(series, bench_series if comparable else None) if len(series) >= 120 else {}
    latest = profile["bars"][-1] if profile["bars"] else None
    quote = {
        "value": latest["c"] if latest else profile["meta"].get("price"),
        "as_of": latest["t"] if latest else profile["meta"].get("price_date"),
        "kind": profile["meta"].get("price_kind"),
        "source": "daily_history" if latest else "profile_snapshot",
    }
    name = _plain(prospectus.get("fund_label") or "") or _plain(report.get("series_name") or "") or hint or ""

    return {
        "ticker": query,
        "cik": (meta or {}).get("cik"),
        "registrant": (meta or {}).get("registrant"),
        "fund_name": name or query,
        "reg_name": report.get("fund_name"),
        "series_name": report.get("series_name"),
        "name_score": report.get("name_score"),
        "identity_warning": "持仓文件与目标基金名称匹配度偏低，请核对申报主体"
        if report.get("name_score") is not None and report.get("name_score") < 0.6
        else None,
        "period_end": report.get("period_end"),
        "net_assets": report.get("net_assets"),
        "total_assets": report.get("total_assets"),
        "pct_float": report.get("pct_float"),
        "share_classes": report.get("share_classes"),
        "primary_class": report.get("primary_class"),
        "filing": report.get("filing"),
        "profile": profile["meta"],
        "quote": quote,
        "history": [{key: bar[key] for key in ("t", "c", "a") if key in bar} for bar in profile["bars"]],
        "return_series": series,
        "return_basis": basis,
        "benchmark": {
            "symbol": "SPY",
            "series": bench_series,
            "basis": bench_basis,
            "comparable": comparable,
        },
        "performance": _period_returns(series),
        "risk": risk,
        "expense": prospectus or {},
        "returns": {
            "months": returns,
            "quarter_total": round((compounded - 1) * 100, 2) if returns else None,
            "annualized": round((compounded ** 4 - 1) * 100, 1) if len(returns) == 3 else None,
        },
        "flows": report.get("flows") or [],
        "analytics": analytics,
        "holdings": holdings[:60],
        "overlap": overlap,
        "source": "sec_edgar_nport" if report.get("holdings") else "nasdaq",
    }
