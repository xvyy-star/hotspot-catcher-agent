# Hotspot Catcher Agent

面向 AI 与计算机技术领域的情报工具，使用 GitHub、Hugging Face、DEV Community、HN 和 arXiv 官方接口。仅发布程序源码和测试样例，不附带采集数据、知识库或账号配置。详见 [数据来源说明](docs/DATA_SOURCES.md)。

项目原创代码采用 [MIT 许可证](LICENSE)。依赖与外部数据不因本项目开源而改变其使用条件；参见 [依赖说明](THIRD_PARTY_NOTICES.md) 和 [安全说明](SECURITY.md)。

> 生产部署请先阅读 `docs/PRODUCTION.md`。  
> 本地开发使用 `.\start.ps1`；生产演练使用 `.\scripts\prod-local-up.ps1`。


AI / 科技行业热点情报 Agent。系统每天从公开数据源采集 AI、开源、开发者社区、科技资讯与产业财经热点，完成去重、评分、RAG 关联、风险判断和结构化简报生成，并支持 QQ / OneBot 推送。

## 当前交付重点

- **聚焦单一主线**：默认只做 AI / 计算机行业 / 开源技术 / 产品情报，不再混入考公或泛娱乐热搜。
- **可追溯数据链路**：原始来源、采集源健康、运行记录、知识库引用都可回看。
- **上线运维可观测**：新增系统日志与数据看板，可直接查看启动、异常、采集、模型、RAG、推送等关键指标。
- **模型成本口径**：模型通道可配置输入/输出单价（USD / 百万 Token），调用日志按当时价格固化预估成本，并提供 24 小时与 7 日趋势。
- **管理员登录态**：新增密码登录、个人中心、退出登录、失败锁定和身份信息接口，避免后台裸入口。
- **安全默认值**：`/api` 默认需要后端管理凭据，模型 Key 会加密入库，外部探测和写操作有基础限流。
- **可行动简报**：首页优先展示“今日情报、可信度、下一步动作”，配置类能力收敛到管理与诊断区。

## 技术栈

- Backend：FastAPI、SQLAlchemy、MySQL、Redis、APScheduler、OpenAI-compatible API、Qdrant
- Frontend：Vue 3、Vite、Element Plus、lucide-vue-next
- Push：OneBot v11 / QQ Bot

## 快速启动

需要 Python 3.11、Node.js 22、Docker Compose 和 PowerShell 7。以下命令在项目根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe scripts\setup_local.py
.\start.ps1
```

启动脚本会优先复用 `hotspot-agent-*` 容器现有端口映射；如果默认依赖端口被其他项目占用，会自动选择空闲端口并同步本次后端连接配置，不会停止其他项目。后端启动前会执行 `scripts/prepare_database.py`，兼容未打 Alembic 版本标签的旧库并升级到当前 head。

前端默认地址：[http://localhost:5173](http://localhost:5173)  
后端健康检查：[http://localhost:8000/health](http://localhost:8000/health)

本地登录：

- 管理员账号：`admin`
- 管理员密码：由 `.env` 中的 `ADMIN_PASSWORD_BCRYPT` 校验；使用 `python scripts/hash_password.py` 生成或重置哈希。

常用脚本：

```powershell
.\start.ps1
.\check.ps1
.\check.ps1 -AdminPassword '<current admin password>'
.\check.ps1 -RequireReady -AdminPassword '<current admin password>'
.\scripts\release-check.ps1 -Target Production
.\stop.ps1
.\stop.ps1 --docker
```

默认验收不会猜测或读取明文管理员密码，密码登录与会话吊销检查会标记为 `SKIP`。需要验证完整登录闭环时，显式传入 `-AdminPassword`，或仅为当前进程设置 `CHECK_ADMIN_PASSWORD` 后运行 `check.ps1`；脚本不会输出该值。正式交付使用 `release-check.ps1`，它会以 `SecureString` 读取密码并按运行形态选择真实 API/UI 入口；严格模式缺少密码、就绪等级不是 `READY` 或仍有阻塞项都会失败。

生产备份会同步生成 SHA256 与 manifest；`restore-mysql.ps1 -ValidateOnly` 可做只读预检，`test-mysql-recovery.ps1` 会在随机临时数据库中执行真实导入和逐表 `CHECK TABLE`，报告写入 `output/drills`。完整故障与回滚演练见 `docs/OPERATIONS_RUNBOOK.md`。

`release-check.ps1` 会先运行 mock API 的核心交互 E2E，再针对所选 Target 的真实前端入口完成登录、数据看板、真实 API 与退出 E2E；随后 `check.ps1 -RequireReady` 会运行离线 AI 质量回归，复验退出后的旧 token 返回 401，并检查生产就绪状态。

运维入口：

- 前端“个人中心”：查看当前管理员身份、权限范围，并退出登录。
- 前端“数据看板”：聚合采集、任务成功率、模型 Token/成本、RAG、推送、反馈与日志健康度。
- 前端“数据看板 / 上线交付检查”：直接展示生产就绪评分、阻塞项、警告项和修复建议。
- 前端“系统日志”：查看启动、任务、接口异常与人工操作；支持按筛选条件删除，未筛选时删除全部日志。
- 前端“今日情报”：支持对情报标记“有用 / 无关 / 收藏 / 屏蔽”，反馈会写入数据库，影响展示排序；屏蔽项默认不再展示。
- 早报生成：默认走后端异步任务，前端展示 run_id、进度并自动轮询结果，避免长请求阻塞和浏览器超时。
- API：`POST /api/auth/login`、`GET /api/auth/me`、`GET /api/system/metrics`、`GET /api/system/readiness`、`GET /api/system/logs`。

## 重要配置

后端 `.env`：

```env
DATABASE_URL=mysql+pymysql://hotspot:hotspot123@localhost:3307/hotspot_agent?charset=utf8mb4
REDIS_URL=redis://localhost:6380/1
APP_TIMEZONE=Asia/Shanghai

API_AUTH_ENABLED=true
ADMIN_USERNAME=admin
ADMIN_DISPLAY_NAME=系统管理员
ADMIN_ROLE=owner
ADMIN_PASSWORD_BCRYPT='<scripts/hash_password.py 输出的 bcrypt 哈希>'
ADMIN_TOKEN=<change-me-random-admin-token>
APP_SECRET_KEY=<change-me-random-secret-key>
LOGIN_FAILURE_LIMIT=5
LOGIN_LOCK_SECONDS=300
SESSION_TTL_SECONDS=28800
SESSION_REMEMBER_TTL_SECONDS=2592000
TRUSTED_PROXY_COUNT=0
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

AI_API_KEY=
AI_BASE_URL=<your-openai-compatible-endpoint>
AI_MODEL=<your-model-name>
```

`ADMIN_PASSWORD_BCRYPT` 必须使用单引号包裹，避免 Docker Compose 把 bcrypt 中的 `$` 当作变量。直连开发环境使用 `TRUSTED_PROXY_COUNT=0`；只有明确位于一层可信反向代理后时才设为 `1`。

完整 Docker 生产栈还必须设置不同的 `MYSQL_ROOT_PASSWORD` 与 `MYSQL_PASSWORD`；应用密码至少 16 位并使用 URL-safe 字符，生产 Compose 不提供密码回退值。

前端 `frontend/.env`：

```env
VITE_API_BASE_URL=/api
```

前端只保留账号密码登录；登录成功后仅把后端返回的会话凭据保存到当前浏览器 `localStorage`。生产部署必须替换 `ADMIN_TOKEN`、`APP_SECRET_KEY` 和数据库密码。

## 数据真实性要求

- Connector 失败时返回空结果，不再用本地样例、模拟数据或固定演示热点顶替。
- 进入 `raw_item` / `event` / `daily_briefing` 的数据必须同时满足：非样例/非模拟、具备 item 级 `http(s)` 原文链接、符合 AI / 计算机行业主线。
- 前端首页和事件表只展示有原文证据的情报卡；缺少出处的数据会在后端被拦截。
- 数据源健康页会展示拦截数量，包括“拦截样例/模拟”和“拦截无出处”。

## 人工反馈闭环

- `POST /api/hotspots/events/{event_key}/feedback`：写入 `USEFUL`、`IRRELEVANT`、`FAVORITE`、`BLOCK` 四类反馈。
- `DELETE /api/hotspots/events/{event_key}/feedback/{action}`：撤销某类反馈。
- `GET /api/hotspots/events/{event_key}/feedback`：查看反馈明细。
- 首页情报卡会根据反馈调整展示热度；收藏优先展示，屏蔽默认隐藏。
- 数据看板新增“人工反馈闭环”，用于观察正向反馈、负向反馈、收藏和屏蔽数量。

## 异步任务

- `POST /api/hotspots/briefings/generate-async`：提交今日早报生成任务，立即返回 `run_id`。
- `POST /api/hotspots/briefings/{date}/regenerate-async`：异步重生成历史早报。
- `GET /api/hotspots/runs/{run_id}`：查询任务状态、进度、事件数、错误和知识库入库结果。
- 同步生成接口仍保留兼容，但前端默认使用异步接口。

## 上线交付检查

- `GET /api/system/readiness`：返回生产就绪评分、阻塞项、警告项、分类检查结果和优先修复建议。
- 检查范围包括：管理员凭据、默认密码/密钥、CORS、限流、真实数据策略、raw/event 证据链、最近任务数据覆盖、采集源健康、模型 Provider、LLM 成功率、RAG 配置、系统日志、调度、推送、迁移脚手架和交付文档。
- 前端“数据看板”已接入该接口，可直接看到“可部署验收 / 需要关注 / 存在阻塞”的判断。

## 目录结构

```text
backend/app/
  agent/          Agent 编排主流程
  api/            FastAPI 路由
  connectors/     公开数据源 Connector
  core/           配置、安全、Secret 工具
  pipeline/       去重、评分、RAG、分析、简报
  services/       模型、知识库、推送、调度、健康服务
  storage/        数据访问层

frontend/src/
  App.vue         主工作台
  api/            API client
  components/     表格、弹窗、选择器
  views/          知识库页面
```

## 验收命令

首次运行测试先安装 `backend/requirements-dev.txt`。默认 pytest 使用每次新建的临时 SQLite 和内存 Redis，并阻止未 mock 的外部 HTTP 请求；不读取项目 MySQL 数据、不清空真实 Redis。CI 的 MySQL 迁移校验保持独立。

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app

.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend\tests

cd frontend
npm run build
npm run test:e2e
cd ..

.\.venv\Scripts\python.exe scripts\evaluate_ai_quality.py
.\scripts\release-check.ps1 -Target Production
```

## 数据库迁移

本地与 Docker 启动入口会自动执行数据库准备和迁移。手动维护时使用：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_database.py
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

`prepare_database.py` 只在未建立版本基线或核心表缺失时执行兼容性 `create_all`，随后始终执行 Alembic `upgrade head` 并校验最终 revision。不要对结构状态未知的业务库直接执行 `stamp head`。

详见 [数据库迁移](migrations/README.md)。

## 上线前检查

详见 [交付检查](docs/DELIVERY_CHECKLIST.md)。

## 运维演练

备份恢复、故障排查和发布回滚见 [运维手册](docs/OPERATIONS_RUNBOOK.md)。
