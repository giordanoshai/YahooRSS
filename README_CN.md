# YahooRSS — 智能金融新闻管道与自动化 RSS 研报系统

<p align="center">
  <strong><a href="README.md">English</a> | <a href="README_CN.md">简体中文</a></strong>
</p>

> 专为日内与波段交易者打造的高频美股财经新闻采集、事件级去重初筛、大模型分流打分、模式 B 自选股精选推送与每日盘前盘后宏观研报自动化系统。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-SQLite%203-blue.svg)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![3D Visualizer](https://img.shields.io/badge/Interactive-Three.js%203D-cyan.svg)](docs/architecture_3d.html)

---

## 🌟 核心特性与架构亮点

1. **工业级抗反爬采集**：
   - 基于 `curl_cffi` 完整模拟 Chrome 浏览器真实 TLS/JA3 指纹，配合指数退避随机扰动重试，彻底解决 Yahoo Finance 频繁 401/403 封禁难题。
   - 采用多级降级抓取策略（动态 `stream-items` 流、备选 `data-testid` 容器与全局文章锚点兜底）。
   - 内置媒体黑名单（过滤 Motley Fool、Zacks、Simply Wall St 等投顾营销号）。
2. **事件级去重与套路文清洗**：
   - **套路文过滤**：17+ 组高精度财经正则表达式与负向词库，物理阻断退休理财、房贷、401(k)、无脑荐股等无关杂讯。
   - **StoryIndex 罕见词倒排索引**：基于过去 24 小时首发新闻统计词频，通过特征罕见词（`DF <= 2` 且共享命中 `>= 2`）识别同事件的第 N 篇跟踪报道。
   - 重复报道入库打标（`is_duplicate = true`），既保证抓取幂等防重，又完全阻断后续正文抓取与大模型 API 消耗。
3. **两阶段 LLM 分流节能模式 (Token Cost -50%+)**：
   - **阶段一（快速初评）**：单次调用输出重要度 (`High`/`Medium`/`Low`)、情绪打分 (`-1.0` ~ `+1.0`) 与受影响 Tickers。
   - **分流旁路门**：`Low` 级别新闻直接保留原英文标题并落库，**彻底跳过第二次长文摘要调用**，立省 50%+ 接口成本；仅 `High` 与 `Medium` 放行进入深度中文化与核心摘要。
4. **模式 B 自选股二次过滤 (RSS Mode-B)**：
   - `High` 级别：全市场重磅事件，无条件直接推入 RSS；
   - `Medium` 级别：行业个股级事件，联动 `user_watchlist` 自选股池，仅命中关注标的时才推入 RSS；
   - 闭环机制：跳过条目自动标记已处理，防止旧数据卡死轮询队列。
5. **合规 RSS 2.0 与自动维护**：
   - 严格遵循 RFC 2822 时间标准格式（`email.utils.format_datetime` + UTC 偏移），解决各端阅读器时间紊乱。
   - `format_content` 语义化富文本转换（自动高亮 Markdown 标题、中文章节括号、列表、金融逻辑链 `A → B → C`）。
   - 自动维护修剪超过保留天数（默认 2 天）的历史条目，防止 XML 体积无限膨胀。
6. **零门槛 SQLite 3 本地存储（开箱即用）**：
   - 内置轻量高效的 SQLite 3 存储引擎，启用 WAL 高并发模式与线程安全写锁。
   - 程序启动时自动执行表结构检查与默认自选股池初始化，**无需搭建或配置任何外部云数据库**。
7. **美股交易日历驱动的盘前盘后大盘综述**：
   - 集成 `exchange_calendars` (XNYS)，自动识别休市与节假日。
   - 美东 08:45（盘前）与 21:00（盘后）自动聚合时间窗口内全部 `High` 级核心重大新闻，投喂旗舰模型（`nvda-nemotron-120b`）输出买方策略师级宏观综述。
8. **全链路 3D 架构交互演化图**：
   - 内置基于 Three.js 开发的 3D 交互式数据流演化动画（位于 `docs/architecture_3d.html`），可直观查看 10 大核心工序的数据流转、分支路由与实时技术卡片。

---

## 🧭 全链路 10 大核心工序全景

```
[01. 抓取引擎] ──> [02. 初筛与去重] ──> [03. 智能评分] ──> [04. 分流决策门]
                                                                  │
              ┌───────────────────────────────────────────────────┴────────────────┐
              ▼ (Low 级别旁路落库，省 50%+ Token)                                    ▼ (Medium / High 放行)
        [直接落库更新]                                                    [05. 深度总结] & [06. 标题精译]
              │                                                                    │
              └───────────────────────────────┬────────────────────────────────────┘
                                              ▼
                                      [07. 二次筛选 (模式 B)]
                                      (High 直接推; Medium 需命中自选池)
                                              │
                                              ▼
                                      [08. 添加到 RSS 2.0]
                                              │
                                              ▼
                                      [09. 清理过期 RSS]
                                              │
                                     (定时美东 08:45 / 21:00)
                                              ▼
                                   [10. 盘前盘后大盘宏观总结]
```

### 10 节点技术规格详解

| 节点序号 | 节点名称 | 核心职责 | 核心算法 / 关键技术 |
| :--- | :--- | :--- | :--- |
| **01** | **数据抓取** | 高频采集 Yahoo Finance 首页与流式新闻 | `curl_cffi` (Chrome TLS 指纹)、`trafilatura` 正文抽取、`ThreadPoolExecutor` 并发 |
| **02** | **初筛去重** | 拦截营销套路文，识别同事件重复报道 | 17+ 组正则表达式、`StoryIndex` 罕见词倒排索引 (`RARE_DF <= 2`)、冷启动保护 |
| **03** | **智能初评** | 评定重要度 (High/Med/Low)、情绪与标的 | `deepseek-v4-flash`、JSON Mode 约束、单次调用零成本提取情绪与 Tickers |
| **04** | **分流决策门** | 区分高低优先级，优化 API 成本 | 分流控制阀：`Low` 级别直接旁路落库，跳过长文模型调用，节约 50%+ 算力 |
| **05** | **深度总结** | 提炼客观紧凑事实摘要 (<=150字) | 事实约束 Prompt 工程、严禁主观幻觉、提取涉事主体与数据变化 |
| **06** | **标题精译** | 英文标题转换为地道金融中文标题 | 结合上下文消除歧义、复合 Prompt 与深度总结单次合并调用消除网络延迟 |
| **07** | **二次筛选** | RSS 入池把关 (模式 B 规则) | `High` 全局推入；`Medium` 需与 `user_watchlist` 有交集；未命中标记跳过闭环 |
| **08** | **添加到 RSS** | 生成符合规范的 RSS 2.0 XML 文件 | `xml.etree.ElementTree`、RFC 2822 时间、`format_content` 逻辑链富文本转换 |
| **09** | **清理 RSS** | 修剪过期条目，保持 XML 轻量 | 滑动窗口截断（默认 2 天）、UTC 时区安全解析、自动修剪节点 |
| **10** | **每日大盘总结** | 生成交易日盘前/盘后买方宏观策略研报 | APScheduler、`exchange_calendars` (XNYS)、`nvda-nemotron-120b` 买方策略 Prompt |

---

## 🎮 3D 架构交互演化图

项目内置了基于 **Three.js** 开发的高品质 3D 交互式可视化流转图：

- **文件路径**：`docs/architecture_3d.html`
- **直接使用**：双击该文件或在本地任意浏览器中打开即可运行，无需构建或额外启动服务。
- **功能特性**：
  - 🌌 赛博高科技 3D 空间，动态光柱与轨道环绕核心节点；
  - ⚡ 实时曲面管道流动粒子，区分主流、Low 级别旁路与大盘宏观聚合分支；
  - 🖱️ 支持 3D 节点点击、悬停、聚焦漫游与平滑相机运镜；
  - 📑 点击任意节点可滑出详尽的**业务逻辑、核心技术、实现代码与输入输出数据示例**抽屉；
  - ⏱️ 支持流速调节、自动全流程巡游、单步前进/后退演进与视角重置。

---

## 🚀 快速上手

### 1. 克隆项目与安装依赖

```bash
git clone https://github.com/giordanoshai/YahooRSS.git
cd YahooRSS

# 建议使用虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装必要依赖
pip install -r requirements.txt
```

### 2. 数据库（开箱即用）

项目采用内置 **SQLite 3** 引擎（启用 WAL 高并发与线程安全锁机制）。
首次运行脚本时，程序会自动完成数据库表与初始自选股池的建立，**无需搭建或配置任何外部数据库服务**。

### 3. 配置环境变量

复制配置文件模版：

```bash
cp .env.example .env
```

打开 `.env` 文件，填入你的大模型 API 密钥：

```ini
# 本地 SQLite 路径（默认无需改动）
SQLITE_DB_PATH=yahoonews.db

# 阿里云 DashScope (用于快速初评、翻译与摘要)
QWEN_API_KEY=sk-your-qwen-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# OpenRouter (用于每日买方大盘综述)
OPENROUTER_API_KEY=sk-or-your-key

# 代理配置 (如在国内运行访问 Yahoo Finance)
# HTTP_PROXY=http://127.0.0.1:7890
```

### 4. 运行应用

```bash
# 启动全自动后台守护进程（高频抓取 + 美东 08:45 / 21:00 定时研报）
python main.py

# 立即执行单次抓取测试
python main.py --once

# 手动触发今日盘前总结研报
python main.py --premarket

# 手动触发今日盘后总结研报
python main.py --postmarket
```

生成的 RSS 文件默认保存在项目根目录下：
- 新闻订阅源：`yahoonews_rss.xml`
- 大盘宏观研报源：`summary_rss.xml`

你可以直接使用 Netlify / Cloudflare Pages / Nginx / 宝塔面板 将这两个 XML 文件静态托管，即可在各大 RSS 阅读器（NetNewsWire、Feedly、Inoreader 等）中实时订阅！

---

## 📂 项目结构

```
YahooRSS/
├── core/
│   ├── config.py           # 环境变量与应用配置 (含 SQLite 路径)
│   ├── database.py         # 本地 SQLite3 数据库交互层 (WAL并发、新闻CRUD、模式B过滤)
│   ├── llm_client.py       # OpenAI 兼容多模型客户端 (Qwen, DeepSeek, Nemotron)
│   └── logger.py           # 日志按日轮转模块
├── scrapers/
│   ├── base_scraper.py     # 抓取器抽象基类 (curl_cffi Chrome 指纹 + trafilatura)
│   └── yahoo_finance.py    # Yahoo Finance 专用高频新闻抓取器
├── services/
│   ├── news_filter.py      # 17+ 正则套路文清洗与 StoryIndex 罕见词事件去重
│   ├── translator.py       # 大模型智能初评、Low 级别旁路路由与深度摘要翻译
│   ├── daily_summary.py    # 盘前盘后大盘宏观研报生成器 (XNYS 交易日历驱动)
│   ├── prompts.py          # 买方策略师结构化提示词库
│   └── rss_generator.py    # RSS 2.0 XML 生成器 (RFC 2822 时间、语义化 HTML、旧条目修剪)
├── docs/
│   ├── architecture_3d.html# 基于 Three.js 的全链路 3D 架构交互演化图
│   └── pipeline_flow.html  # 数据流水线交互式看板
├── main.py                 # APScheduler 统一调度入口
├── CHANGELOG.md            # 版本变更追踪记录
├── PLAN.md                 # 架构重构与开发计划
├── .env.example            # 环境变量模版
├── requirements.txt        # Python 依赖清单
├── README.md               # 英文说明文档
└── README_CN.md            # 中文说明文档
```

---

## ⚖️ 免责声明 (Disclaimer)

本系统生成的所有新闻摘要、情绪打分、关联标的与每日宏观研报均由大语言模型基于公开网络资讯自动归纳生成，仅供技术研究与个人参考，**不构成任何投资建议或要约**。金融市场具有高风险性，投资决策请保持独立思考并审慎评估风险。

## 📄 License

本项目采用 [MIT License](LICENSE) 开源协议。

