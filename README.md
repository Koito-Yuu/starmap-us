# 星图 STARMAP · 美股投研终端

星图是一个本地运行的中文美股研究工作台。后端使用 FastAPI 聚合公开行情、SEC EDGAR、FRED、纳斯达克与美联储官方数据；前端使用原生 ES Modules 与 ECharts，无构建步骤。覆盖市场全景、个股研究、自选研究、智能选股、多股对比、组合回测、宏观雷达与基金档案。

## 目录

- [快速开始](#快速开始)
- [功能地图](#功能地图)
- [数据来源与口径](#数据来源与口径)
- [个股研究](#个股研究)
- [自选研究](#自选研究)
- [组合回测](#组合回测)
- [智能选股](#智能选股)
- [宏观雷达](#宏观雷达)
- [工程架构](#工程架构)
- [API](#api)
- [配置](#配置)
- [已知限制](#已知限制)
- [研究参考](#研究参考)

---

## 快速开始

要求 Python 3.11+，并能够访问下列公开数据源。

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS / Linux

.venv/Scripts/python.exe app.py
# 或指定监听地址
.venv/Scripts/python.exe app.py --host 0.0.0.0 --port 8000
```

打开 <http://127.0.0.1:8000>。API 文档位于 <http://127.0.0.1:8000/docs>。

首次启动会在后台预热市场快照。选股页的全量快照按需抓取，首次打开可能需要数十秒；市场总览与个股同业只加载前 3,000 只，避免首屏等待。

界面默认亮色，支持暗色主题、中式/美式红绿配色、可折叠侧栏、自选拖拽排序、全局搜索（`/` 或 `Ctrl/Cmd + K`）与移动端布局。字体为 Inter + Noto Sans SC，数字使用等宽数字。

---

## 功能地图

| 模块 | 核心能力 |
| --- | --- |
| 市场总览 | 主要指数、行业 ETF、涨跌/活跃榜、市场宽度、市值热力图、宏观快照、财报日历与 7×24 资讯 |
| 个股研究 | K 线与可参数化技术指标、关键价位、SEC 财务深读、现金流、MD&A 文本洞察、分析师、同业、申报、股息与新闻 |
| 自选研究 | 等权自选指数、相对 SPY、趋势宽度、行业构成、相关性矩阵、技术标签、排序、批量对比与组合衔接 |
| 智能选股 | 全市场快照、6 组策略、估值/动量/股息/行业过滤、排序分页、自选标记与 CSV 导出 |
| 多股对比 | 最多 6 只标的归一化走势、回撤、风险收益散点、相关性矩阵与风险指标 |
| 组合回测 | 目标权重、多个本地组合、1Y/3Y/5Y 回测、周期再平衡、风险贡献、集中度、滚动风险、回撤阶段与收益归因 |
| 宏观雷达 | 35 条 FRED 序列、FOMC 官方日历/声明、政策走廊、资产负债表、经济周期象限、期限结构、信用与衰退观察 |
| 基金档案 | 共同基金/ETF 档案、N-PORT 持仓、月度申赎、集中度、费率、业绩与自选重叠 |

### 设计原则

- **来源可追溯**：行情、财务、宏观和文本数据分别标注来源与 as-of；降级数据不伪装成主源。
- **不补造数据**：缺失价格、成交量、指标窗口或基金份额类别时留空，不用代理数据填补。
- **描述而非预测**：技术指标、宏观象限、衰退观察和风险分解都是描述性工具，不输出收益承诺或伪概率。
- **本地优先**：自选、组合与图表偏好保存在浏览器 localStorage。

---

## 数据来源与口径

| 来源 | 用途 | 说明 |
| --- | --- | --- |
| 东方财富 push2 / push2his | 报价、历史 K 线、全市场快照、财务主指标、公司资料、资讯 | 优先行情源；K 线使用前复权 |
| 腾讯行情 | 报价备用、快照估值与动量补全 | 东方财富报价或快照不可用时 |
| Nasdaq | 历史行情备用、基金/ETF 日线、分析师、股息、财报日历、全市场快照备用 | 备用日线为原始收盘价 |
| SEC EDGAR | XBRL 三大报表、10-K/10-Q/20-F、MD&A、风险因素、N-PORT、497K | 需要合规的 User-Agent |
| FRED | 利率、通胀、就业、信用、流动性与增长序列 | 发布频率与修订机制不同 |
| Federal Reserve Board | FOMC 日历、声明、纪要、SEP 官方链接 | 只展示官方原文，不推算点阵图中位数或降息概率 |

缓存采用内存 + `.cache/` 磁盘 JSON，按数据类型设置 30 秒–30 天 TTL；过期条目采用 stale-while-revalidate，先返回旧值并在后台刷新，上游失败时回退到过期缓存（stale-on-error）。启动时会预热市场总览与选股快照；东方财富实时接口不可用时先尝试编号镜像，再降级到腾讯与 Nasdaq，腾讯批量补全 PE、PB、股息率、60 日与年内涨跌。界面会区分真实周期、数据来源与复权口径，不重复显示成功的回退提示。

### 行情口径

- 东方财富 K 线为前复权价格；Nasdaq 备用行情为原始收盘价，两者不混算。
- 短区间会在可见 K 线之前额外获取同源同周期历史用于指标预热，返回序列严格与可见 K 线对齐。
- 缺失价格、成交量和不足窗口不会被填充或补造，对应指标留空。
- K 线未收盘时，最新一根会随行情变化；历史数据也可能被上游修订。

### 基金口径

- 共同基金显示单位净值，ETF 显示收盘市价；价格与日期取自同一条日线。
- 全段具备 Nasdaq `adjustedClose` 时使用复权序列计算收益，否则整段采用价格收益，不逐日混用两种口径。
- SPY 与基金口径不兼容时不计算 Beta、相关性或涨跌捕获率。
- N-PORT 有披露滞后；ETF 备用持仓可能仅含前十大。无法唯一确认份额类别时不作猜测性映射。

---

## 个股研究

### 图表与技术分析

行情图采用右侧价格轴、跨面板联动十字光标、双指/滑块缩放和简洁图例，默认绘制关键价位与最新价标记。

- **基础**：MA5/10/20/50/200、成交量均线、MACD、RSI、对数坐标。
- **六种主图通道**：布林、肯特纳、唐奇安、滚动回归、滚动量价、自适应波动通道。
- **趋势叠加**：Supertrend 与 KAMA。
- **六种副图**：ADX/DMI、慢速随机、CMF、OBV、ATR%、BB/KC 收缩动量。
- **参数**：均线、MACD、RSI，以及当前通道、趋势线、副图的周期与倍数均可调整；参数保存在本机，切换指标时保留图表缩放。
- **关键价位**：从最近 180 根 K 线提取局部摆动高低点，取最近支撑与压力并做距离聚合；仅作结构参考，不是交易信号。
- **研究视角**：经典、趋势跟踪、区间突破、波动收缩、量价确认、回归结构。

计算口径与局限集中展示在“指标手册”。所有指标只使用当前及以前的数据，不使用未来值。

### 财务与 SEC

`/api/stocks/{symbol}/statements` 提供：

- 年度/季度三大报表与比率矩阵；
- 毛利率、净利率、FCF 利润率、ROE、ROIC、现金转换周期、应计比率、杠杆、有效税率与 Rule of 40；
- 营收/FCF CAGR、毛利率和 ROIC 变化、股东回报与资本配置；
- 基于事实比率的可追溯解读。

不展示 Altman Z、Piotroski、Beneish 或自定义综合质量评分。

申报列表优先展示 10-K、10-Q、8-K、DEF 14A 等实质性文件，并保证最新年报出现；标签统一为完整的 `FORM 10-K` 形式，长表单在共享网格中换行而不截断。

### MD&A 文本洞察

`/api/stocks/{symbol}/mda` 在最新年报、上一份年报和最新 10-Q 之间构建文本分析：

- 从 HTML 中剔除表格噪声后提取 Item 7 / 7A（10-K）或 Part I Item 2（10-Q）章节；
- 按经营业绩、产品/分部、流动性与资本资源、关键会计估计、展望、市场风险等主题拆分内容；
- 基于句子角色与关键词权重生成“管理层摘要”，覆盖经营表现、资本配置、流动性、展望、会计估计和风险；
- 提取带指标、期间和数值的量化指引候选，过滤免责声明；无正式指引时不补造；
- 计算金融措辞密度、不确定性、主题强度与可读性；
- 对比上一份年报：章节占比、主题密度、句级新增/减少/改写、指引数量和风险因素变化；
- 核心摘录保留原文句子，不调用在线 LLM，不生成原文没有的事实。

文本分析是启发式提取：章节标题不规范、表格引用、PDF 附件或非标准申报结构都可能降低召回率。句级差异用于定位披露重点，不代表事实发生变化。

---

## 自选研究

自选已提升为一级导航页面，同时保留侧栏快捷行情。

- 等权自选指数对照 SPY，支持 3M / 6M / 1Y；
- 上涨/下跌家数、等权收益、MA20/50/200 宽度、平均相关性与离散度；
- 行业构成、最强/最弱月度标的、技术标签（超买、超卖、放量、接近高点、深回撤等）；
- 每只标的的 1W/1M/3M/YTD 收益、RSI、相对强弱、52 周位置与近 3 月迷你走势；
- 排序、增删、批量对比前 6 只，或一键带入组合回测；
- 相关性矩阵使用完整共同日收益，未对齐区间不强行插值。

自选指数是**监控指标**（归一收盘价均值），不是可交易组合。

---

## 组合回测

组合页不是账本，也不要求录入买卖流水。它回答的问题是：**给定一组股票和目标权重，这个组合过去表现如何？**

- 1–20 只股票、目标权重；权重不必恰好等于 100%，后端会归一化并展示归一后的权重；
- 保存多组命名组合到本机，后续载入并重新回测；
- 基准：SPY、QQQ、IWM、DIA；
- 区间：1Y / 3Y / 5Y；再平衡：买入持有、月度、季度、年度；
- 输出：净值与回撤曲线、年度收益、目标配置、成分表现、换手估算，以及 CAGR、年化波动、Sharpe、Sortino、最大回撤、Calmar、VaR/CVaR、Beta、相关性、跟踪误差、信息比率和上下行捕获；
- **组合诊断**：有效持仓数、HHI、分散化比率、有效风险来源、逐仓风险贡献与权重偏离、持仓相关性矩阵、60 日滚动波动率/Beta；
- **回撤与压力**：按峰值—谷底—修复划分的主要回撤阶段，以及历史实际滚动最差 20 / 60 个交易日，组合与基准并列；
- **收益贡献**：按持仓日盈亏累计除以初始本金，逐仓贡献合计严格等于组合区间收益；另列平均漂移权重、风险占比和风险预算差；
- 修改持仓或回测参数后，结果区会标记“待更新”，旧结果不会被误当作新参数的结果；
- 回测严格使用持仓与基准的共同交易日；历史不足 60 天或任一成分缺行情时停止，不用代理数据补洞；
- 风险贡献使用目标权重与全区间日收益协方差，属于事后分解；压力窗口是历史最差区间，不是假设情景或未来预测；
- **未计佣金、滑点、税费与冲击成本**，结果仅为历史模拟；不同来源或复权口径可能影响成分收益。

当前股票池不含已退市证券，因此存在幸存者偏差。

---

## 智能选股

- **全市场快照**：按需抓取东方财富全市场，上限 14,000 只，按总市值排序；结果缓存 20 分钟。降级合并快照不缓存，便于上游恢复后立即切回全量。
- **分级降级**：东方财富不可用时，先合并最近一次东方财富缓存与 Nasdaq 全量——前 3,000 只保留估值/动量字段，其余补充 Nasdaq 行情；两者都不可用时才使用纯 Nasdaq 快照。Nasdaq 补充部分已剔除权证、单位、优先股、债券等非普通股。
- **字段覆盖**：合并模式下 PE/PB/股息/动量只覆盖东方财富缓存部分，界面显示覆盖率；纯 Nasdaq 备用模式下这些字段不可用，相关筛选会禁用。
- **策略预设**：高质量成长、低估值价值、强势动量、股息收益、超跌观察、巨头俱乐部。
- **筛选维度**：代码/公司名、行业、市值、PE、PB、股息率、60 日涨幅与年内涨幅。
- **交互**：实时筛选、列排序、分页、自选标记、CSV 导出；过滤后结果与导出范围一致。

全量快照只影响选股页；市场总览、热力图与个股同业对比继续使用前 3,000 只，以控制首屏负载。

---

## 宏观雷达

宏观页围绕“环境分类”而非“预测”构建，当前接入 35 条 FRED 序列，并整合 Federal Reserve Board 的 FOMC 官方日程与声明。

- **利率与曲线**：3M / 2Y / 5Y / 10Y / 30Y、10Y-2Y、10Y-3M、30Y-5Y、牛陡/熊陡/牛平/熊平；
- **通胀与实际利率**：CPI、核心 CPI、核心 PCE 同比、3 个月年化、10Y 实际利率、10Y 盈亏平衡、5y5y 远期通胀；
- **经济周期**：CFNAI 3 月均值 × 核心 CPI 同比的四象限，展示最近 36 个月轨迹；分类不是衰退概率；
- **就业**：失业率、Sahm 近似、初请 4 周均值与同比、非农月度增量；
- **信用与流动性**：高收益债 OAS、Baa-10Y、NFCI、M2 同比、美联储总资产同比；
- **美联储与 FOMC**：目标区间上下限、EFFR、SOFR、IORB、实际政策利率、总资产、准备金、ON RRP；下一次会议倒计时、未来会议、最近声明要点、纪要及 SEP/点阵图官方链接；
- **独立衰退观察**：10Y-3M 倒挂、Sahm 规则、初请趋势、CFNAI、HY OAS、NFCI；每项只显示“触发 / 观察 / 未触发 / 数据不足”，不合成总分或概率。

重要限制：

- FOMC 声明、纪要与 SEP 只展示官方原文和链接，不自行推算点阵图中位数、降息概率或政策路径；
- **不显示自定义的“衰退概率”**。只有采用公开模型且完整披露样本、参数和 as-of 时才可作为概率；
- CFNAI、Sahm、非农、初请和信用利差是同步或确认型指标，不是精确计时器；期限利差虽有领先性，但时滞不稳定；
- FRED 从 2026 年起对高收益债 OAS 只保留约 3 年窗口，因此同时提供 Baa-10Y 作为长历史参照。两者评级范围不同，不能拼接成一条序列；
- 各序列发布频率和修订机制不同，界面分别展示 as-of；不要假设它们在同一时刻更新。

---

## 工程架构

```
us/
├── app.py                         # 本地启动入口
├── server/
│   ├── app.py                     # FastAPI 应用、静态资源、异常映射
│   ├── config.py                  # 数据源、宏观序列、市场与区间配置
│   ├── data/
│   │   ├── http.py                # 共享异步 HTTP 客户端、重试与节流
│   │   ├── cache.py               # TTL 缓存 + 磁盘持久化 + stale-on-error
│   │   ├── eastmoney.py           # 报价、K 线、全市场快照、财务、资料、资讯
│   │   ├── nasdaq.py              # 历史行情、基金/ETF、分析师、股息、备用快照
│   │   ├── tencent.py             # 报价备用
│   │   ├── sec.py / edgar.py      # EDGAR 索引、XBRL、财务分析、MD&A/风险文本
│   │   ├── flows.py               # 现金流轻量解析
│   │   ├── fred.py                # FRED 与通胀/就业/信用/周期派生指标
│   │   ├── fomc.py                # FOMC 官方日历、声明、纪要与 SEP 链接
│   │   ├── watchlist.py           # 自选聚合、宽度、相关性与行业
│   │   ├── funds.py               # 基金身份、N-PORT、497K、风险
│   │   └── analysis.py            # 技术指标、对比、组合回测与风险
│   └── routers/                   # market/stocks/watchlist/screener/compare/portfolio/macro/funds
└── web/
    ├── index.html
    └── assets/
        ├── css/                   # app、watchlist、macro、portfolio、mda
        ├── js/                    # api/store/technical/charts/ui
        │   └── views/             # overview/stock/watchlist/screener/.../fund
        └── vendor/echarts.min.js
```

前端使用 hash 路由：`#/overview`、`#/stock/NVDA`、`#/watchlist`、`#/screener`、`#/compare?symbols=AAPL,MSFT&range=1Y`、`#/portfolio`、`#/macro`、`#/fund/VTSAX`。

### 性能策略

- 个股首屏复用 `/overview` 内嵌 K 线与指标，切换区间才按需请求；
- 指标参数化后，短区间仍只取一次同源历史；默认参数不产生额外请求，修改参数时只重算指标；
- 宏观、财务、文本与基金数据分层缓存；SEC 抓取全局限速，MD&A 首次解析较慢，缓存后为毫秒级；
- 全市场快照按需加载并单独缓存，市场总览与个股同业不承担全量快照成本；
- ECharts 实例集中注册，路由切换释放实例与 ResizeObserver；长序列使用 LTTB 与稀疏日期标签；
- 前端 GET 响应带短 TTL 内存缓存；上游返回错误时不缓存错误结果。

---

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/market/status` | 美股交易时段 |
| GET | `/api/market/overview` | 指数、板块、宽度、榜单、资讯、宏观快照 |
| GET | `/api/market/earnings` | 财报日历 |
| GET | `/api/search?q=` | 标的搜索 |
| GET | `/api/quotes?symbols=` | 批量报价 |
| GET | `/api/stocks/{symbol}/overview?params=` | 个股聚合数据；可选技术指标参数 JSON |
| GET | `/api/stocks/{symbol}/chart?range=1Y&params=` | K 线与对齐后的指标序列 |
| GET | `/api/stocks/{symbol}/financials` | 财务主指标 |
| GET | `/api/stocks/{symbol}/statements` | SEC 三大报表、比率、趋势与资本配置 |
| GET | `/api/stocks/{symbol}/mda` | MD&A、风险因素、主题、指引、同比句级变化 |
| GET | `/api/stocks/{symbol}/cashflow` | SEC 现金流轻量接口 |
| GET | `/api/stocks/{symbol}/filings` | SEC 申报列表 |
| GET | `/api/stocks/{symbol}/news` | 个股新闻 |
| GET | `/api/watchlist/analyze?symbols=&range=` | 自选等权指数、宽度、产业、相关性与逐股快照 |
| GET | `/api/screener/universe?limit=14000` | 全市场快照 |
| GET | `/api/screener/presets` | 预设策略 |
| GET | `/api/compare?symbols=&range=` | 归一化走势、回撤、风险指标、相关性 |
| POST | `/api/portfolio/backtest` | 目标权重组合回测 |
| GET | `/api/macro/overview` | 宏观卡片、FOMC、周期、利率、信用与观察规则 |
| GET | `/api/macro/fomc` | FOMC 官方日历、最近声明、纪要与 SEP 链接 |
| GET | `/api/macro/series/{id}?years=10` | 单条 FRED 序列 |
| GET | `/api/funds/{ticker}?watch=` | 基金/ETF 价格、收益、费率、持仓与自选重叠 |

组合回测请求示例：

```json
{
  "holdings": [
    { "symbol": "AAPL", "weight": 40 },
    { "symbol": "MSFT", "weight": 35 },
    { "symbol": "NVDA", "weight": 25 }
  ],
  "range": "3Y",
  "rebalance": "quarterly",
  "benchmark": "SPY"
}
```

---

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `US_CACHE_DIR` | `<项目>/.cache` | 缓存目录 |
| `US_CACHE_DISABLE` | 空 | 设为 `1` / `true` 关闭缓存（调试用） |
| `SEC_CONTACT` | 内置说明字符串 | SEC 请求 User-Agent 联系信息，建议改为自己的邮箱 |

命令行参数：`--host`（默认 `127.0.0.1`）、`--port`（默认 `8000`）。

---

## 已知限制

- 上游均为公开但非官方承诺的接口，可能限流、变更或短时不可用；系统会重试、轮换镜像、切换备用源和过期缓存，但无法保证 100% 可用。
- 行情可能延迟，盘前/盘后覆盖有限；Nasdaq 备用日线未复权。
- 全市场快照优先取东方财富；失败时先合并最近缓存与 Nasdaq，再回退纯 Nasdaq。补充部分缺少 PE/PB/股息/动量字段，筛选覆盖率会下降。快照不是 point-in-time 历史成分，不能直接用于严谨的无幸存者偏差回测。
- 技术指标、关键价位、宏观象限和衰退观察规则都是描述性工具，不是收益保证或交易建议。
- MD&A 抽取是规则系统，复杂表格、异常标题和非 HTML 附件可能降低准确率；句级差异只用于定位披露变化。
- 自选和组合保存在浏览器 localStorage，清理浏览器数据会丢失；没有多用户隔离。
- 宏观序列存在发布滞后与修订，最新修订值不等于当时的实时值；不能用于严谨的 point-in-time 回测。

---

## 研究参考

界面与指标的取舍参考了以下公开项目与资料：

**技术分析 / 图表**

- [TA-Lib](https://ta-lib.org/)：经典指标分类与 Wilder 平滑
- [ta](https://technical-analysis-library-in-python.readthedocs.io/)：趋势、动量、波动与量价分类
- [Stock.Indicators](https://python.stockindicators.dev/indicators/)：预热与序列一致性
- [Pandas TA Classic](https://xgboosted.github.io/pandas-ta-classic/indicators.html)：Supertrend、KAMA、Squeeze 表达
- [TradingView 指标设置](https://www.tradingview.com/support/solutions/43000480333-how-to-adjust-the-indicator-settings/) 与 [价格轴文档](https://www.tradingview.com/charting-library-docs/latest/ui_elements/Price-Scale)
- [Bloomberg Terminal Charts](https://professional.bloomberg.com/products/bloomberg-terminal/charts/)：高密度图表与信息层级参考

**SEC / 文本**

- [edgartools](https://github.com/dgunning/edgartools)：Filing → Section → Table 的对象化思路
- [sec-parser](https://github.com/alphanome-ai/sec-parser)：语义元素与 Part/Item 层级
- [edgar-crawler](https://github.com/nlpaueb/edgar-crawler)：Item schema 与降级策略
- [Loughran-McDonald](https://sraf.nd.edu/loughranmcdonald-master-dictionary/)：金融文本词典分类
- [TextRank](https://aclanthology.org/W04-3252/)：抽取式摘要的句子权重思想
- [17 CFR 229.303](https://www.law.cornell.edu/cfr/text/17/229.303)：MD&A 披露要求

**组合 / 自选**

- [QuantStats](https://github.com/ranaroussi/quantstats)：风险指标公式
- [Portfolio Visualizer](https://www.portfoliovisualizer.com/backtest-portfolio)：目标权重回测与再平衡
- [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/)：风险贡献与组合构建概念
- [TradingView Watchlists](https://www.tradingview.com/support/solutions/43000745825-mastering-the-tradingview-watchlists/)：多列表与筛选联动
- [OpenBB](https://github.com/OpenBB-finance/OpenBB)：数据组件与终端信息架构

**宏观**

- [Federal Reserve FOMC 日历、声明与纪要](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
- [FRED 目标区间上限 DFEDTARU](https://fred.stlouisfed.org/series/DFEDTARU) / [下限 DFEDTARL](https://fred.stlouisfed.org/series/DFEDTARL)
- [NY Fed 收益率曲线研究](https://www.newyorkfed.org/medialibrary/media/research/current_issues/ci2-7.pdf)
- [Sahm 规则](https://fred.stlouisfed.org/series/SAHMREALTIME)
- [芝加哥联储 CFNAI](https://www.chicagofed.org/research/data/cfnai/current-data) / [NFCI](https://www.chicagofed.org/research/data/nfci/current-data)
- [ribromeu/US-Yield-Curve-Macro-Dashboard](https://github.com/ribromeu/US-Yield-Curve-Macro-Dashboard)
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/) / [ALFRED](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)