# YahooRSS — Intelligent Financial News Pipeline & Automated RSS System

<p align="center">
  <strong><a href="README.md">English</a> | <a href="README_CN.md">简体中文</a></strong>
</p>

> High-frequency US stock market news harvesting, event-level inverted index deduplication, dual-stage LLM evaluation & summarization, Mode-B watchlist filtering, and automated pre/post-market macro research digests for intraday and swing traders.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-SQLite%203-blue.svg)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![3D Visualizer](https://img.shields.io/badge/Interactive-Three.js%203D-cyan.svg)](docs/architecture_3d.html)

---

## 🌟 Key Features & Architectural Highlights

1. **Industrial Anti-Bot Scraping Engine**:
   - Built on `curl_cffi` to replicate genuine Chrome TLS / JA3 fingerprints with randomized exponential backoff retry schedules, eliminating 401/403 rate limits on Yahoo Finance.
   - Multi-tier fallback extraction (`stream-items` feed, backup `data-testid` containers, and global article anchor heuristics).
   - Integrated publisher blacklisting to drop promotional syndicates (Motley Fool, Zacks, Simply Wall St, etc.).
2. **Event-Level Deduplication & Heuristic Cleansing**:
   - **Clickbait Cleansing**: 17+ targeted financial regex patterns and negative keyword dictionaries discard retirement, mortgage, 401(k), and formulaic penny stock noise before persistence.
   - **StoryIndex Rare-Word Inverted Index**: Computes document frequencies across primary news over a 24-hour sliding window; events sharing `>= 2` rare tokens (`DF <= 2`) are recognized as follow-up coverage of an existing event.
   - Secondary reports are ingested with `is_duplicate = true` for immutable auditing while halting subsequent body scraping and LLM API consumption.
3. **Dual-Stage LLM Routing (-50%+ Token Cost)**:
   - **Stage 1 (Rapid Appraisal)**: Single-call evaluation yields importance level (`High`/`Medium`/`Low`), market sentiment (`-1.0` to `+1.0`), and affected stock tickers with zero extra cost.
   - **Bypass Decision Gate**: `Low` impact news bypasses the 2nd LLM call and persists a lightweight formatted card, cutting token expenditure by over 50%; only `High` and `Medium` proceed to in-depth bilingual translation and concise fact extraction.
4. **Mode-B Watchlist Secondary Filtering**:
   - `High` Impact: Systemic market catalysts directly pushed to RSS.
   - `Medium` Impact: Sector-specific news pushed to RSS only when affected tickers intersect with the `user_watchlist` portfolio pool.
   - Closed-Loop Queue: Discarded items are immediately tagged as processed (`is_rss = true`), preventing queue bottlenecks.
5. **RFC 2822 Compliant RSS 2.0 with Auto-Pruning**:
   - Strictly conforms to RFC 2822 datetime formatting (`email.utils.format_datetime` + UTC offset) to eliminate client-side timezone drift.
   - Semantic HTML styling with highlighted Markdown headings, categorized financial tags, and logical inference chains (`A → B → C`).
   - Automated sliding-window retention (default 2 days) prunes outdated XML nodes, preventing infinite file bloat.
6. **Zero-Configuration Local SQLite3 Storage**:
   - Embedded SQLite3 engine running in WAL mode with a 15-second busy timeout and thread-safe write locks.
   - Auto-initializes schema, indices, and default high-volume watchlist tickers on startup—**no cloud database setup required**.
7. **NYSE/XNYS Calendar-Driven Macro Summaries**:
   - Integrates `exchange_calendars` (XNYS) to verify active US trading sessions and federal holidays.
   - Fires at 08:45 ET (Pre-Market) and 21:00 ET (Post-Market) to aggregate `High` impact news, prompting flagship models (`nvda-nemotron-120b`) to formulate buy-side macro strategy reports.
8. **Interactive 3D Pipeline Visualizer**:
   - Includes a standalone Three.js 3D visualizer (`docs/architecture_3d.html`) rendering live particle telemetry, bypass flows, and interactive node specification drawers.

---

## 🧭 10-Step Pipeline Architecture

```
[01. Ingestion Engine] ──> [02. Filter & Dedup] ──> [03. LLM Scoring] ──> [04. Routing Gate]
                                                                                  │
              ┌───────────────────────────────────────────────────────────────────┴────────────────┐
              ▼ (Low Impact Bypass: Save 50%+ Tokens)                                              ▼ (Medium / High)
       [Direct DB Save]                                                                    [05. Deep Fact Summary] & [06. Title Translation]
              │                                                                                            │
              └─────────────────────────────────┬──────────────────────────────────────────────────────────┘
                                                ▼
                                    [07. Mode-B Watchlist Filter]
                                    (High: Global; Medium: Watchlist Match)
                                                │
                                                ▼
                                    [08. Append to RSS 2.0]
                                                │
                                                ▼
                                    [09. Sliding Window Pruning]
                                                │
                                      (Scheduled 08:45 / 21:00 ET)
                                                ▼
                                    [10. Macro Strategy Synthesis]
```

### 10 Node Technical Specifications

| Step | Node Name | Primary Responsibility | Core Algorithm / Technology |
| :---: | :--- | :--- | :--- |
| **01** | **Ingestion Engine** | High-frequency Yahoo Finance news harvesting | `curl_cffi` (Chrome TLS), `trafilatura`, `ThreadPoolExecutor` |
| **02** | **Filter & Dedup** | Block promotional noise and repetitive wire coverage | 17+ Regex rules, `StoryIndex` rare inverted index (`DF <= 2`), cold-start guards |
| **03** | **LLM Scoring** | Assess importance (`High`/`Med`/`Low`), sentiment & tickers | `deepseek-v4-flash`, strict JSON mode, zero-cost ticker extraction |
| **04** | **Routing Gate** | Separate priorities to optimize model budget | Gate control: `Low` impact bypasses second LLM call, saving 50%+ compute |
| **05** | **Deep Summary** | Extract factual summary (<= 150 words) | Strict prompt constraints, subjective hallucination suppression, metric diffs |
| **06** | **Title Translation** | Localize English titles into authentic financial Chinese | Contextual disambiguation, unified single-pass call with deep summary |
| **07** | **Mode-B Filter** | RSS gatekeeper via user portfolio watchlist | `High` pushed globally; `Medium` requires `user_watchlist` match; skip tag closure |
| **08** | **Append to RSS** | Generate standard-compliant RSS 2.0 XML | `xml.etree.ElementTree`, RFC 2822 dates, logic chain semantic markup |
| **09** | **Sliding Window Prune** | Truncate stale items to maintain lean XML size | Sliding window cutoff (default 2 days), UTC parser, node removal |
| **10** | **Macro Synthesis** | Produce pre-market & post-market strategy reports | APScheduler, `exchange_calendars` (XNYS), `nvda-nemotron-120b` buy-side prompt |

---

## 🎮 Interactive 3D Visualizer

The project comes with a high-fidelity 3D interactive pipeline visualization built with **Three.js**:

- **File Location**: `docs/architecture_3d.html`
- **How to Use**: Double-click or open directly in any standard browser—no build steps or local servers required.
- **Key Capabilities**:
  - 🌌 Futuristic 3D scene with dynamic lighting and orbital node rings;
  - ⚡ Particle pipeline simulations distinguishing primary flow, Low bypass, and macro synthesis branches;
  - 🖱️ Orbit controls: click, hover, focal fly-in, and smooth camera panning;
  - 📑 Comprehensive spec drawer for each node displaying business logic, metrics, and production code snippets;
  - ⏱️ Flow speed sliders, guided tour autoplay, step-by-step playback, and camera reset.

---

## 🚀 Quick Start

### 1. Clone & Set Up Environment

```bash
git clone https://github.com/giordanoshai/YahooRSS.git
cd YahooRSS

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Database (Zero Configuration)

The system uses an embedded **SQLite 3** engine in WAL mode.
Database tables, indices, and default watchlist records are created automatically on first run—**no external database service or SQL import needed**.

### 3. Environment Variables

Create your local `.env` from the provided template:

```bash
cp .env.example .env
```

Configure your model API keys:

```ini
# Local SQLite path (default is ready out of the box)
SQLITE_DB_PATH=yahoonews.db

# DashScope / Qwen / DeepSeek (Fast scoring, translation & summary)
QWEN_API_KEY=sk-your-qwen-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# OpenRouter (Pre/Post-market buy-side macro report synthesis)
OPENROUTER_API_KEY=sk-or-your-key

# Optional Proxy (if running inside regions requiring proxies)
# HTTP_PROXY=http://127.0.0.1:7890
```

### 4. Run the Pipeline

```bash
# Start background daemon (continuous scraping + scheduled 08:45 / 21:00 ET macro reports)
python main.py

# Run a single harvest cycle immediately
python main.py --once

# Trigger today's pre-market macro synthesis report manually
python main.py --premarket

# Trigger today's post-market macro synthesis report manually
python main.py --postmarket
```

Generated RSS feeds are saved in the project root:
- News Feed: `yahoonews_rss.xml`
- Macro Research Feed: `summary_rss.xml`

Deploy these static XML files via Netlify, Cloudflare Pages, Nginx, or GitHub Pages to subscribe in NetNewsWire, Feedly, Inoreader, etc.

---

## 📂 Project Structure

```
YahooRSS/
├── core/
│   ├── config.py           # Configuration manager and SQLite paths
│   ├── database.py         # SQLite 3 data access layer (WAL mode, thread-safe write locks)
│   ├── llm_client.py       # OpenAI-compatible multi-provider LLM client
│   └── logger.py           # Daily rotating logger
├── scrapers/
│   ├── base_scraper.py     # Base scraper with curl_cffi Chrome TLS fingerprinting
│   └── yahoo_finance.py    # Yahoo Finance streaming news scraper
├── services/
│   ├── news_filter.py      # 17+ regex cleaning & StoryIndex rare-word deduplication
│   ├── translator.py       # Dual-stage LLM evaluation, Low bypass gate & translation
│   ├── daily_summary.py    # Pre/Post-market macro synthesis (XNYS calendar-driven)
│   ├── prompts.py          # Buy-side prompt templates
│   └── rss_generator.py    # RFC 2822 RSS 2.0 generator with sliding-window pruning
├── docs/
│   ├── architecture_3d.html# Interactive Three.js 3D pipeline visualizer
│   └── pipeline_flow.html  # Interactive data pipeline telemetry board
├── main.py                 # APScheduler unified daemon entry point
├── CHANGELOG.md            # Structured change log
├── PLAN.md                 # Architecture refactor and roadmaps
├── .env.example            # Environment variable template
├── requirements.txt        # Minimal Python dependencies
├── README.md               # English documentation
└── README_CN.md            # Simplified Chinese documentation
```

---

## ⚖️ Disclaimer

All news summaries, sentiment scores, affected tickers, and macro reports generated by this system are automatically processed by large language models from public web sources. They are intended solely for academic research and software demonstration and **do NOT constitute financial, investment, or trading advice**. Financial markets carry substantial risk; conduct your own research and consult licensed professionals before making investment decisions.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
