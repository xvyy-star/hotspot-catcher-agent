# 生产运维与恢复演练手册

本文用于发布验收、MySQL 恢复演练、依赖故障演练和版本回滚。所有命令均从项目根目录执行。生产 Compose 命令统一使用 `.env`，避免示例配置覆盖正式端口和数据库凭据。

## 1. 发布门槛

根据当前运行形态选择一个入口：

```powershell
# 开发栈：API 8000，前端 5173
.\scripts\release-check.ps1 -Target Development

# 本地生产预览：API 8000，前端 4173
.\scripts\release-check.ps1 -Target ProductionLocal

# 完整 Docker 生产栈：API 和前端均通过 FRONTEND_PORT，默认 8080
.\scripts\release-check.ps1 -Target Production
```

脚本会用 `SecureString` 交互读取管理员密码，先执行 mock API 的核心交互 E2E，再针对所选 Target 的真实入口执行部署 E2E，最后调用 `check.ps1 -RequireReady`。严格检查还会执行离线 AI 质量回归，不请求外部模型。自动化环境使用仅对当前进程有效的变量：

```powershell
$env:CHECK_ADMIN_PASSWORD = '<current admin password>'
.\scripts\release-check.ps1 -Target Production -NonInteractive
Remove-Item Env:CHECK_ADMIN_PASSWORD
```

Playwright 会优先使用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`，否则自动查找本机 Chrome/Edge；没有可用浏览器时执行 `cd frontend; npx playwright install chromium`。`-SkipE2E` 仅用于故障恢复过程中的快速重复探测，正式发布留证不使用该开关。

发布通过条件：

- API 与前端实际入口可访问；
- mock E2E 覆盖登录、主导航、模型配置和 QQ 推送，真实部署 E2E 覆盖目标 bundle、真实 API、数据看板与退出；
- `scripts/evaluate_ai_quality.py` 的分类、排序、事实、引用和无依据断言门槛全部通过；
- `/health`、`/readyz` 和依赖检查通过；
- 管理员登录、会话签发、退出和吊销均通过，旧会话 token 复用返回 401；
- `/api/system/readiness` 返回 `READY` 且 `blockers=0`；
- 冒烟数据全部清理，汇总为 `failed=0`。

直接调用 `check.ps1` 时也可以指定入口：

```powershell
.\check.ps1 -RequireReady `
  -AdminPassword '<current admin password>' `
  -ApiBaseUrl http://127.0.0.1:8080 `
  -FrontendUrl http://127.0.0.1:8080
```

严格模式缺少管理员密码时会失败，不会以 `SKIP` 代替登录闭环。

`start.ps1` 与生产 backend 容器会在启动应用前执行 `scripts/prepare_database.py`，自动升级到 Alembic head。发布前先备份；迁移命令退出非零时停止发布，不绕过迁移直接拉起应用。

## 2. MySQL 备份与静态校验

生产备份：

```powershell
$backupFile = .\scripts\backup-mysql.ps1 -Prod | Select-Object -Last 1
$backupFile
```

每次备份生成三个同名文件：

- `mysql_yyyyMMdd_HHmmss_fff_<id>.sql`：原始 `mysqldump`，毫秒时间与随机后缀避免覆盖同秒备份；
- `.sql.sha256`：文件校验值；
- `.sql.manifest.json`：库名、栈、表数量、大小、校验值和时间。

不连接数据库、不写数据的预检：

```powershell
.\scripts\restore-mysql.ps1 -BackupFile $backupFile -Prod -ValidateOnly
```

预检会从 `.env` 和 `-Prod` 解析目标栈与目标库，并验证 dump 头、完成标记、建表语句、文件大小、SHA256、manifest 必填字段，以及 manifest 中 `stack` / `database` 与目标完全一致。它不会检查 Docker 或连接 MySQL，也不会修改数据库；缺少校验文件、manifest、目标不匹配或任一硬校验失败均返回非零退出码。

正式恢复始终要求完整 SHA256 与 manifest，`-AllowLegacyBackup` 仅可用于 `test-mysql-recovery.ps1` 的隔离演练，不能用于 `restore-mysql.ps1`。

## 3. 隔离恢复演练

每周以及每次数据库迁移前后执行：

```powershell
.\scripts\test-mysql-recovery.ps1 -BackupFile $backupFile -Prod
```

演练流程：

1. 校验备份文件、SHA256 和 manifest，并确认源备份的栈与业务库匹配 `-Prod` 目标；
2. 在同一 MySQL 容器创建随机命名的临时数据库；
3. 将 SQL 导入临时数据库；
4. 比对 manifest 表数量并通过 MySQL 协议逐表运行 `CHECK TABLE`；
5. 删除临时数据库和容器临时文件；
6. 将结果写入 `output/drills/mysql-recovery_yyyyMMdd_HHmmss.json`。

演练不会写入业务数据库。`success=true`、`cleanup_ok=true` 且退出码为 `0` 才算通过。

## 4. 正式恢复步骤

1. 先对目标备份完成隔离恢复演练；人工备份仍建议保留，正式恢复脚本也会在修改目标库前自动生成独立回滚备份。
2. 记录 `docker compose --env-file .env -f docker-compose.prod.yml ps` 输出。
3. 停止写流量：

```powershell
docker compose --env-file .env -f docker-compose.prod.yml stop frontend backend
```

4. 再次预检目标备份，随后显式确认恢复：

```powershell
.\scripts\restore-mysql.ps1 -BackupFile $backupFile -Prod -ValidateOnly
.\scripts\restore-mysql.ps1 -BackupFile $backupFile -Prod -ConfirmRestore
```

`-ConfirmRestore` 会再次执行完整预检，然后按以下顺序工作：

- 将当前业务库备份为 `output/backups/mysql_pre_restore_*.sql`，生成 SHA256 与 manifest 并完成自校验；
- 保留原库字符集和排序规则，删除并重新创建目标库，确保不会把备份叠加到现有表；
- 使用 root 账户导入目标备份，并比对恢复后的表数量；
- 任一步骤在目标库开始变化后失败时，自动再次重建目标库并导入回滚备份；
- 无论自动回滚是否成功，原始恢复失败都返回非零退出码，并在输出中保留回滚备份路径与回滚状态。

看到 `[restore] Done` 后再启动写流量；看到任一 `[restore] FAIL` 时保持应用停止，根据输出核对自动回滚结果。

5. 拉起应用并执行严格门槛：

```powershell
docker compose --env-file .env -f docker-compose.prod.yml start backend frontend
.\scripts\release-check.ps1 -Target Production
```

6. 核对最近任务、热点数量、知识库文档和系统日志时间范围。保留恢复前备份、目标备份、演练 JSON 和严格验收输出。

## 5. 依赖故障演练

演练前必须完成一次生产备份与严格验收。每次只注入一个故障，不使用 `down -v`，并记录故障开始、发现、恢复和验收时间。

### MySQL

```powershell
docker stop hotspot-agent-prod-mysql
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8080/readyz
docker start hotspot-agent-prod-mysql
```

预期：故障期间 `/readyz` 非 `200`；MySQL 恢复后应用自动重连，严格验收通过，业务数据量未下降。

### Redis

```powershell
docker stop hotspot-agent-prod-redis
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8080/readyz
docker start hotspot-agent-prod-redis
```

预期：就绪检查能发现 Redis 中断；恢复后登录、限流、调度锁和异步任务状态可用。

### Qdrant

```powershell
docker stop hotspot-agent-prod-qdrant
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8080/readyz
docker start hotspot-agent-prod-qdrant
```

预期：就绪检查能发现向量库中断；恢复后知识库检索可用，已有 collection 数量保持一致。

### 后端进程

```powershell
docker kill hotspot-agent-prod-backend
docker inspect --format "{{.RestartCount}} {{.State.Status}}" hotspot-agent-prod-backend
```

预期：`restart: unless-stopped` 自动拉起容器，`/readyz` 恢复，未出现永久停留在 `RUNNING` 的异步任务。

每项恢复后执行：

```powershell
.\scripts\release-check.ps1 -Target Production
docker compose --env-file .env -f docker-compose.prod.yml ps
```

建议验收目标：故障在 60 秒内被发现，单容器恢复在 180 秒内完成，严格门槛最终通过。实际 RTO/RPO 按部署资源重新基线化。

## 6. 发布回滚

发布前保留当前镜像与数据快照：

```powershell
$rollbackTag = Get-Date -Format "yyyyMMdd-HHmmss"
docker tag hotspot-catcher-agent-backend:latest "hotspot-catcher-agent-backend:rollback-$rollbackTag"
docker tag hotspot-catcher-agent-frontend:latest "hotspot-catcher-agent-frontend:rollback-$rollbackTag"
$preReleaseBackup = .\scripts\backup-mysql.ps1 -Prod | Select-Object -Last 1
.\scripts\test-mysql-recovery.ps1 -BackupFile $preReleaseBackup -Prod
```

需要回滚时：

```powershell
docker compose --env-file .env -f docker-compose.prod.yml stop frontend backend
docker tag "hotspot-catcher-agent-backend:rollback-$rollbackTag" hotspot-catcher-agent-backend:latest
docker tag "hotspot-catcher-agent-frontend:rollback-$rollbackTag" hotspot-catcher-agent-frontend:latest
docker compose --env-file .env -f docker-compose.prod.yml up -d --no-build --force-recreate backend frontend
```

仅当新版本已经执行不兼容的数据迁移或写入错误数据时，再恢复 `$preReleaseBackup`。回滚完成后执行严格验收，并检查 Alembic 版本与回滚镜像预期版本一致。

## 7. 演练记录模板

每次演练至少记录：

| 字段 | 内容 |
| --- | --- |
| 发布版本/镜像 ID | backend、frontend 镜像摘要 |
| 操作人和时间 | 开始、发现、恢复、结束 |
| 备份 | SQL 路径、SHA256、manifest |
| 故障类型 | MySQL、Redis、Qdrant、backend 或版本回滚 |
| RTO/RPO | 实测秒数、数据时间点 |
| 自动验收 | `release-check.ps1` 退出码 |
| 恢复演练 | JSON 报告路径与 `success` |
| 遗留问题 | 负责人、截止时间、复验结果 |

备份应复制到独立存储并定期执行异地副本恢复演练；只生成 SQL 文件但没有恢复验证，不计为有效备份闭环。
