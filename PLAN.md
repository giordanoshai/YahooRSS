# YahooRSS 迁移至 SQLite3 数据库重构计划

## 目标
将 YahooRSS 从云端 Supabase (PostgreSQL) 迁移到本地轻量高效的 SQLite3 数据库，实现零配置开箱即用，彻底降低开源用户使用门槛，同时保证多线程高并发下的数据一致性与稳定性。

## 任务拆解与当前进度

- [x] **Step 1: 数据库 DDL 与表结构适配 (`database.sql`)**
  - 转换为 SQLite3 兼容的 DDL 语法。
  - 标的数组改用 JSON 字符串存储与检索。
  - 建立必要的高效索引（published_at, is_duplicate, is_rss 等）。
- [x] **Step 2: 配置项与环境变量调整 (`core/config.py`, `.env.example`)**
  - 引入 `SQLITE_DB_PATH`（默认 `yahoonews.db`）。
  - 移除对 Supabase URL / Key 的强制依赖。
- [x] **Step 3: 核心数据库模块彻底重构 (`core/database.py`)**
  - 基于 Python 内置 `sqlite3` 实现全量 CRUD。
  - 启用 WAL 模式与 `busy_timeout=15000`。
  - 针对多线程环境引入线程局部连接 (`threading.local`) 与写锁保护 (`threading.Lock`)。
  - 启动时自动初始化建表，支持开箱即用。
  - 保持各层外部函数签名与返回结构 100% 契约一致。
- [x] **Step 4: 依赖清理与自动化测试验证**
  - `requirements.txt` 移除外部 `supabase` / `postgrest` 依赖。
  - 运行自动化验证脚本，覆盖新闻增删改查、去重、RSS 模式 B 筛选与宏观总结（9 项测试 100% 通过）。
- [x] **Step 5: 开源文档与架构说明同步更新**
  - 更新 `README.md`、`docs/` 相关架构图与说明。
  - 更新 `CHANGELOG.md`。
