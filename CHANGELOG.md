# Changelog

### [2026-11-04] 发布准备：移除冗余 database.sql 与分支收敛
* **修改 (Changed)**: 彻底移除运行期非必需的 `database.sql`，全量建表交由 Python 代码零配置自初始化；恢复并适配 3D 架构交互图；准备发布至开源 `main` 主分支。

### [2026-11-04] 双语文档标准化与开源发布清理
* **新增 (Added)**: 引入中英双语文档架构，将默认 `README.md` 升级为国际化英文规范文档，并提供完整的中文镜像文档 `README_CN.md`。
* **修复 (Fixed)**: 彻底清理个人测试脚本 `test_daily_summary.py` 及临时测试数据库残留，确保开源工作区与 Git 仓库结构极致纯净。
* **修改 (Changed)**: 更新中英文文档中的项目目录树与架构说明，使其与纯净的 SQLite3 本地架构严格保持一致。

### [2026-11-04] 数据库架构重构：全面切换为本地 SQLite3 引擎
* **新增 (Added)**: 引入本地 SQLite3 自动初始化与建表机制，支持开箱即用；增加 `SQLITE_DB_PATH` 配置，具备 WAL 高并发模式与多线程写互斥锁保护。
* **修复 (Fixed)**: 彻底解耦对外部云端 Supabase / PostgreSQL 服务的强依赖，精简 `requirements.txt` 中冗余的第三方数据库 SDK（`supabase`, `postgrest`）。
* **修改 (Changed)**: 重写 `core/database.py` 内部 CRUD 与事件过滤实现，数据表 DDL (`database.sql`) 适配 SQLite3 语法；同步更新 `README.md`、`docs/` 交互文档与配置模板 `.env.example`。

### [2026-11-04] 开源前环境清理与安全去敏
* **新增 (Added)**: 创建 CHANGELOG.md 追踪版本与代码变更记录。
* **修复 (Fixed)**: 移除含钉钉凭证的测试脚本 `test_dingtalk.py`、私有数据库迁移脚本 `import_notes.py` 及二进制日志 `test_result.log`，彻底杜绝敏感凭证与冗余文件泄漏风险。
* **修改 (Changed)**: 清理本地遗留的大型 SQLite 数据库文件（`yahoonews_large.db` 361MB 等）、废弃旧版本模块目录 `Old/`、历史测试数据目录 `json/` 及过期运行日志 `logs/`，使仓库与工作区满足纯净开源标准。
