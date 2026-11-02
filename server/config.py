from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
CACHE_DIR = Path(os.getenv("US_CACHE_DIR", str(BASE_DIR / ".cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SEC_CONTACT = os.getenv(
    "SEC_CONTACT", "Starmap US Equity Research (contact: zhengriya@gmail.com)"
)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

EASTMONEY_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
NASDAQ_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
SEC_HEADERS = {
    "User-Agent": SEC_CONTACT,
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
}
FRED_HEADERS = {"User-Agent": "StarmapResearch/1.0"}

HTTP_TIMEOUT = 24.0
HTTP_RETRIES = 2

US_MARKETS = (105, 106, 107)
MARKET_NAMES = {105: "NASDAQ", 106: "NYSE", 107: "AMEX"}
MARKET_SUFFIX = {105: "O", 106: "N", 107: "A"}

SECTOR_ETFS = [
    {"symbol": "XLK", "secid": "107.XLK", "name": "信息技术"},
    {"symbol": "XLC", "secid": "107.XLC", "name": "通讯服务"},
    {"symbol": "XLY", "secid": "107.XLY", "name": "可选消费"},
    {"symbol": "XLP", "secid": "107.XLP", "name": "日常消费"},
    {"symbol": "XLF", "secid": "107.XLF", "name": "金融"},
    {"symbol": "XLV", "secid": "107.XLV", "name": "医疗保健"},
    {"symbol": "XLI", "secid": "107.XLI", "name": "工业"},
    {"symbol": "XLE", "secid": "107.XLE", "name": "能源"},
    {"symbol": "XLB", "secid": "107.XLB", "name": "原材料"},
    {"symbol": "XLU", "secid": "107.XLU", "name": "公用事业"},
    {"symbol": "XLRE", "secid": "107.XLRE", "name": "房地产"},
]

INDEX_CARDS = [
    {"symbol": "SPX", "secid": "100.SPX", "name": "标普 500", "kind": "index"},
    {"symbol": "COMP", "secid": "100.NDX", "name": "纳斯达克综合", "kind": "index"},
    {"symbol": "DJIA", "secid": "100.DJIA", "name": "道琼斯工业", "kind": "index"},
    {"symbol": "IWM", "secid": "107.IWM", "name": "罗素 2000", "kind": "etf"},
]

MACRO_SERIES = {
    "DGS10": {"label": "10 年期美债收益率", "unit": "%", "freq": "d", "kind": "rate"},
    "DGS2": {"label": "2 年期美债收益率", "unit": "%", "freq": "d", "kind": "rate"},
    "DGS3MO": {"label": "3 个月美债收益率", "unit": "%", "freq": "d", "kind": "rate"},
    "DGS5": {"label": "5 年期美债收益率", "unit": "%", "freq": "d", "kind": "rate"},
    "DGS30": {"label": "30 年期美债收益率", "unit": "%", "freq": "d", "kind": "rate"},
    "T10Y2Y": {"label": "10Y-2Y 利差", "unit": "%", "freq": "d", "kind": "spread"},
    "CPIAUCSL": {"label": "CPI 同比", "unit": "%", "freq": "m", "kind": "inflation", "yoy": True},
    "CPILFESL": {"label": "核心 CPI 同比", "unit": "%", "freq": "m", "kind": "inflation", "yoy": True},
    "UNRATE": {"label": "美国失业率", "unit": "%", "freq": "m", "kind": "labor"},
    "FEDFUNDS": {"label": "联邦基金利率", "unit": "%", "freq": "m", "kind": "rate"},
    "DFEDTARU": {"label": "联邦基金目标区间上限", "unit": "%", "freq": "d", "kind": "rate"},
    "DFEDTARL": {"label": "联邦基金目标区间下限", "unit": "%", "freq": "d", "kind": "rate"},
    "EFFR": {"label": "有效联邦基金利率 EFFR", "unit": "%", "freq": "d", "kind": "rate"},
    "SOFR": {"label": "担保隔夜融资利率 SOFR", "unit": "%", "freq": "d", "kind": "rate"},
    "IORB": {"label": "准备金余额利率 IORB", "unit": "%", "freq": "d", "kind": "rate"},
    "RRPONTSYD": {"label": "隔夜逆回购规模", "unit": "billion USD", "freq": "d", "kind": "liquidity"},
    "WRESBAL": {"label": "银行准备金余额", "unit": "million USD", "freq": "w", "kind": "liquidity"},
    "VIXCLS": {"label": "VIX 恐慌指数", "unit": "", "freq": "d", "kind": "volatility"},
    "DTWEXBGS": {"label": "美元指数（广义）", "unit": "", "freq": "d", "kind": "dollar"},
    "GDPC1": {"label": "美国实际 GDP 同比", "unit": "%", "freq": "q", "kind": "growth", "yoy": True},
    "UMCSENT": {"label": "密歇根消费者信心", "unit": "", "freq": "m", "kind": "sentiment"},
    "T10Y3M": {"label": "10Y-3M 利差", "unit": "%", "freq": "d", "kind": "spread"},
    "DFII10": {"label": "10 年期实际收益率", "unit": "%", "freq": "d", "kind": "rate"},
    "T10YIE": {"label": "10 年期盈亏平衡通胀", "unit": "%", "freq": "d", "kind": "inflation"},
    "T5YIFR": {"label": "5y5y 远期通胀预期", "unit": "%", "freq": "d", "kind": "inflation"},
    "BAMLH0A0HYM2": {"label": "美国高收益债 OAS", "unit": "%", "freq": "d", "kind": "credit"},
    "BAA10Y": {"label": "Baa-10Y 信用利差", "unit": "%", "freq": "d", "kind": "credit"},
    "NFCI": {"label": "芝加哥联储金融条件指数", "unit": "index", "freq": "w", "kind": "conditions"},
    "CFNAI": {"label": "芝加哥联储全国活动指数", "unit": "index", "freq": "m", "kind": "activity"},
    "ICSA": {"label": "美国初请失业金人数", "unit": "人", "freq": "w", "kind": "labor"},
    "PAYEMS": {"label": "美国非农就业人数", "unit": "千人", "freq": "m", "kind": "labor"},
    "PCEPILFE": {"label": "核心 PCE 物价指数", "unit": "index", "freq": "m", "kind": "inflation", "yoy": True},
    "PERMIT": {"label": "美国新屋许可", "unit": "千套", "freq": "m", "kind": "housing"},
    "M2SL": {"label": "美国 M2 货币供应", "unit": "billion USD", "freq": "m", "kind": "liquidity"},
    "WALCL": {"label": "美联储总资产", "unit": "million USD", "freq": "w", "kind": "liquidity"},
}

# NYSE / Nasdaq full-day closures used for the market clock (2026).
MARKET_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
}

RANGE_MAP = {
    "1D": {"klt": 5, "lmt": 78, "intraday": True},
    "5D": {"klt": 15, "lmt": 130, "intraday": True},
    "1M": {"klt": 101, "lmt": 24, "intraday": False},
    "3M": {"klt": 101, "lmt": 68, "intraday": False},
    "6M": {"klt": 101, "lmt": 135, "intraday": False},
    "YTD": {"klt": 101, "lmt": 260, "intraday": False},
    "1Y": {"klt": 101, "lmt": 260, "intraday": False},
    "3Y": {"klt": 101, "lmt": 780, "intraday": False},
    "5Y": {"klt": 101, "lmt": 1300, "intraday": False},
    "MAX": {"klt": 102, "lmt": 1200, "intraday": False},
}
