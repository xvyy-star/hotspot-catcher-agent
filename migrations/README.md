# Alembic 数据库迁移

项目已提供 baseline 和后续版本化 revision。启动阶段不再执行 `ALTER TABLE` 自动补列；所有结构变更统一通过 Alembic 管理。

常用命令：

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe scripts\prepare_database.py
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

上线建议：

1. 本地与生产启动入口默认执行 `scripts/prepare_database.py`，为无版本标签的旧库建立兼容基线，再执行 `upgrade head`。
2. 迁移前先备份并完成隔离恢复演练；迁移失败时停止发布。
3. 后续表结构变更只通过 revision 管理；生产环境设置 `AUTO_CREATE_TABLES=false`。
4. `stamp head` 只用于人工确认结构与 head 完全一致的特殊修复，不作为常规升级命令。
