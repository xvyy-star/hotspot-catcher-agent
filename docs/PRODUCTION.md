# Hotspot Catcher Agent 生产化部署说明

当前项目已经具备准生产能力：登录鉴权、系统日志、数据大屏、真实来源证据、反馈记录、模型配置、知识问答和部署自检均可用。正式生产部署时按下面方式落地。

## 1. 必填环境变量

复制 `.env.example` 为 `.env` 后，至少修改：

```env
ADMIN_PASSWORD_BCRYPT='<使用 python scripts/hash_password.py 生成>'
ADMIN_TOKEN=替换为随机长令牌
APP_SECRET_KEY=替换为随机长密钥
AI_API_KEY=你的模型服务 Key
AI_BASE_URL=https://你的模型网关/v1
AI_MODEL=你的模型名
CORS_ORIGINS=http://你的域名
FRONTEND_PORT=8080
TRUSTED_PROXY_COUNT=1
AUTO_CREATE_TABLES=false
APP_TIMEZONE=Asia/Shanghai
MYSQL_ROOT_PASSWORD=至少16位随机值
MYSQL_DATABASE=hotspot_agent
MYSQL_USER=hotspot
MYSQL_PASSWORD=至少16位URL-safe随机值
# 可选：部署网络访问官方 PyPI 较慢时配置可信的 Python 包镜像。
# PIP_INDEX_URL=https://your-python-package-mirror/simple
```

不要配置明文 `ADMIN_PASSWORD`。bcrypt 哈希要使用单引号包裹，避免其中的 `$` 被 Docker Compose 展开。

`MYSQL_ROOT_PASSWORD` 与 `MYSQL_PASSWORD` 都是生产必填项，必须不同；`prod-up.ps1` 会在构建前检查缺失、示例值、长度和应用密码的 URL-safe 字符约束。

## 2. 一键启动可验证生产形态

```powershell
# Run from the repository root.
.\scripts\prod-local-up.ps1
```

启动后访问：

- 应用：http://127.0.0.1:4173
- 健康检查：http://127.0.0.1:4173/health
- 就绪检查：http://127.0.0.1:4173/readyz

该方式会：

- 启动 MySQL / Redis / Qdrant。
- 兼容旧数据库基线并自动执行 Alembic `upgrade head`。
- 启动 FastAPI 后端。
- 执行前端 `npm run build`。
- 用 Vite preview 服务已构建的 `dist` 产物。
- 使用 `/readyz` 判断 MySQL / Redis / Qdrant / 后端是否可接流量。

停止前端生产预览：

```powershell
.\scripts\prod-local-down.ps1
```

## 3. 可选：完整 Docker 生产栈

如果部署机器能稳定拉取 Python / Node / Nginx 镜像并安装 pip/npm 依赖，可使用完整容器栈：

```powershell
.\scripts\prod-up.ps1
```

默认访问：

- 应用：http://127.0.0.1:8080
- 就绪检查：http://127.0.0.1:8080/readyz

生产栈包含：

- `frontend`：Nginx 静态站点 + `/api` 反向代理
- `backend`：FastAPI
- `mysql`：业务数据
- `redis`：缓存/限流
- `qdrant`：知识库向量检索

后端容器在启动 Uvicorn 前执行 `scripts/prepare_database.py`；迁移失败时容器不会进入可接流量状态。发布前仍需先完成数据库备份和隔离恢复演练。

所有服务均配置 `restart: unless-stopped`，容器异常退出后会自动恢复。

## 4. 停止完整 Docker 生产栈

```powershell
.\scripts\prod-down.ps1
```

默认保留数据卷。确实要删除全部数据时才执行：

```powershell
docker compose --env-file .env -f docker-compose.prod.yml down -v
```

## 5. 本地开发启动

开发模式仍使用：

```powershell
.\start.ps1
.\check.ps1
.\check.ps1 -AdminPassword '<current admin password>'
```

`start.ps1` 现在会等待 MySQL / Redis / Qdrant 就绪，并使用 `/readyz` 判断后端是否真的可用；如果后端进程存在但依赖不可用，会自动重启后端。

## 6. 上线前验收

每次部署后运行：

```powershell
.\check.ps1
.\scripts\release-check.ps1 -Target Production
```

第一条针对开发端口执行基础接口和数据清理验收，密码登录/退出检查会显示为 `SKIP`；第二条先执行 mock API 核心交互 E2E，再针对完整生产栈实际暴露的 `FRONTEND_PORT` 运行真实登录、数据看板、API 与退出 E2E，并启用离线 AI 质量回归和 `READY` 严格交付门槛。脚本还会复用已退出的旧 token 验证返回 401。密码以 `SecureString` 读取；自动化环境也可通过当前进程的 `CHECK_ADMIN_PASSWORD` 环境变量提供。严格模式缺少密码会直接失败。

必须满足：

- `/readyz dependencies` 为 OK
- mock 核心 E2E 与真实部署 E2E 全部通过
- `AI quality regression gate` 为 OK
- `Deployment readiness API` 为 `READY`
- `blockers=0`
- `Check summary` 中 `failed=0`
- `Auth password login API`、`Auth logout revokes session` 与旧 token 复验均为 OK

模型通道还应在“模型配置”中填写输入、输出单价，单位为 `USD / 百万 Token`。调用日志会按调用发生时的价格固化 `estimated_cost`，之后调整单价不会改写历史成本。

## 7. 备份与恢复

开发栈备份：

```powershell
.\scripts\backup-mysql.ps1
```

生产栈备份：

```powershell
$backupFile = .\scripts\backup-mysql.ps1 -Prod | Select-Object -Last 1
```

备份同时生成 `.sha256` 和 `.manifest.json`。先执行只读预检，再在随机临时数据库完成导入与逐表 `CHECK TABLE` 演练：

```powershell
.\scripts\restore-mysql.ps1 -BackupFile $backupFile -Prod -ValidateOnly
.\scripts\test-mysql-recovery.ps1 -BackupFile $backupFile -Prod
```

正式恢复前停止前后端写流量，再显式确认：

```powershell
docker compose --env-file .env -f docker-compose.prod.yml stop frontend backend
.\scripts\restore-mysql.ps1 -BackupFile $backupFile -Prod -ConfirmRestore
docker compose --env-file .env -f docker-compose.prod.yml start backend frontend
.\scripts\release-check.ps1 -Target Production
```

恢复演练报告写入 `output/drills/mysql-recovery_yyyyMMdd_HHmmss.json`。完整故障注入、镜像回滚、RTO/RPO 与留证步骤见 `docs/OPERATIONS_RUNBOOK.md`。

## 8. 自动拉起 / 守护

Windows 服务器可用计划任务每分钟执行一次：

```powershell
.\scripts\watchdog.ps1
```

它会检查 `http://127.0.0.1:8000/readyz`，如果 MySQL / Redis / Qdrant / 后端不可用，会自动调用 `start.ps1` 拉起并写入：

```text
output/watchdog/watchdog.log
```

## 9. 仍需外部配套

真正公网生产还需要：

1. 域名和 HTTPS 证书。
2. 服务器级监控告警，例如 CPU、内存、磁盘、容器状态。
3. 定时备份任务。
4. 日志归档策略。
5. 模型 API Key 轮换流程。
6. 外部推送通道真实配置。

## 10. 运维演练

上线前至少完成一次 MySQL 隔离恢复演练；上线后按季度执行 MySQL、Redis、Qdrant、backend 单点故障演练和镜像回滚演练。执行命令、验收标准与记录模板见 `docs/OPERATIONS_RUNBOOK.md`。
