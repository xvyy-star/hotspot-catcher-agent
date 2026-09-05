# 交付检查清单

## P0 必须完成

- [x] 默认聚焦 AI / 科技行业热点，不再把泛热点作为主线。
- [x] `/api` 默认启用后端管理凭据。
- [x] 前端密码登录页、个人中心与退出登录。
- [x] 登录失败锁定与登录/退出审计日志。
- [x] 系统日志支持按当前筛选条件批量删除；无筛选时删除全部。
- [x] 前端 API Client 登录后自动携带后端返回的会话凭据。
- [x] 模型 API Key 保存前加密，返回时只脱敏。
- [x] 写操作与高频读取有基础限流。
- [x] 采集源实时探测有缓存，避免反复请求外部公开源。
- [x] raw item 7 天内重复采集幂等复用，降低数据库膨胀。
- [x] 前端首页从“功能后台”调整为“今日情报工作台”。
- [x] 移动端保留可打开的侧边导航。
- [x] 一键启动、停止、健康检查脚本。
- [x] 移除演示数据重置脚本，避免把样例数据误当真实数据。
- [x] 基础接口测试。
- [x] Alembic 迁移脚手架和 baseline。
- [x] 前端首次使用引导。
- [x] 热点可信度评分和来源解释。
- [x] 系统日志中心：启动、人工操作、任务结束、接口异常可查询。
- [x] 轻量数据看板：采集、模型、RAG、推送、日志核心指标一屏可看。
- [x] 任务、模型、Token、预估成本、推送与反馈的 7 日运营趋势。
- [x] 模型输入/输出单价配置与调用时成本固化。
- [x] 上线交付检查：后端 `/api/system/readiness` 输出生产就绪评分、阻塞项、警告项和修复建议，前端数据看板可视化展示。
- [x] Playwright 核心流程 E2E、独立 AI 质量 gate，以及 MySQL / Redis / Qdrant 支撑的完整后端迁移与测试 CI。

## P0 安全加固（本轮完成）

- [x] **P0-1** 登录签发独立会话 token（Redis 存储），logout 主动吊销，不再返回静态 ADMIN_TOKEN。
- [x] **P0-2** 限流与登录失败锁定迁移到 Redis，多 worker/多实例共享。
- [x] **P0-3** 移除启动时自动 ALTER TABLE 补列迁移，结构变更统一走 Alembic；新增 AUTO_CREATE_TABLES 开关。
- [x] **P0-4** 默认凭据改为空，启动时校验拒绝裸启动；docker-compose 密码用 `${VAR}` 注入。
- [x] **P0-5** 移除 token 的 URL query param 通道，仅允许 Header 传递。
- [x] **P0-6** 同步生成/重生成接口标记 deprecated，前端 API 注释引导使用异步接口。
- [x] **P0-7** 密码校验优先 bcrypt，移除明文密码支持；提供 `scripts/hash_password.py` 生成哈希。
- [x] **P0-8** 生产环境默认关闭 `/docs` `/redoc` `/openapi.json`（DOCS_ENABLED=false）。
- [x] **P0-9** 新增 `test_pipeline.py`（15 个纯函数测试，CI 无依赖运行）；冒烟测试改用 bcrypt 哈希。
- [x] **Bug** 修复 `runner.py:185` 三元表达式两分支相同的复制粘贴 bug。

## P1 建议上线后继续做

- [x] 接入 Alembic 版本化数据库迁移脚手架。
- [x] 将所有历史轻量补列逻辑完全迁入 Alembic revision。
- [x] 本地与生产启动前自动执行兼容性数据库准备和 Alembic head 校验。
- [x] 把“生成简报”改成后端异步 Job + 前端轮询。
- [ ] 从单管理员账号升级到用户体系、团队空间和权限角色。
- [x] 给热点卡片增加“有用/无关/收藏/屏蔽”反馈闭环。
- [ ] 接入 Prometheus / OpenTelemetry / 日志告警。
- [ ] 为 Connector 增加失败类型、SLA 和备用源策略。
- [ ] 为 RAG 分数做模型级归一化，避免不同 embedding 尺度混用。

## 部署安全项

1. 修改 `.env`：
   - `ADMIN_USERNAME`
   - `ADMIN_DISPLAY_NAME`
   - `ADMIN_PASSWORD_BCRYPT`（使用 `scripts/hash_password.py` 生成并以单引号包裹）
   - `ADMIN_TOKEN`
   - `APP_SECRET_KEY`
   - `LOGIN_FAILURE_LIMIT`
   - `LOGIN_LOCK_SECONDS`
   - `DATABASE_URL`
   - `REDIS_URL`
   - `APP_TIMEZONE`
   - `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD`（生产必填且不同）
   - `CORS_ORIGINS`
2. 修改 `frontend/.env`：
   - `VITE_API_BASE_URL`
3. 登录后台“数据看板”，查看“上线交付检查”，优先清零阻塞项，再处理高风险警告项。
4. 不要把真实 API 管理凭据写入前端构建环境变量。
5. 不要暴露 MySQL、Redis、Qdrant 到公网。
6. 生产环境建议用反向代理统一 TLS、访问日志和 IP 限流。
7. QQ / OneBot token 只保存在服务器本地配置或 Secret Manager。

## 验收命令

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
.\.venv\Scripts\python.exe -m pytest backend\tests
cd frontend
npm run build
npm run test:e2e
cd ..
.\.venv\Scripts\python.exe scripts\evaluate_ai_quality.py
.\check.ps1
.\scripts\release-check.ps1 -Target Production
```

普通检查不传密码时，登录/退出闭环会计入 `skipped`，不会使用默认弱口令尝试登录；正式交付使用 `release-check.ps1`，通过实际生产入口完成登录与吊销并要求就绪等级为 `READY`。严格模式缺少管理员密码会失败。

## 生产运维留证

- [ ] 使用 `.env` 启动生产 Compose 栈，确认正式端口和数据库凭据已生效。
- [ ] mock 核心 E2E 与目标入口真实部署 E2E 全部通过，离线 AI 质量报告 `passed=true`。
- [ ] `release-check.ps1 -Target Production` 退出码为 `0`，`failed=0`。
- [ ] 生成 MySQL SQL、SHA256 和 manifest，`restore-mysql.ps1 -ValidateOnly` 通过。
- [ ] `test-mysql-recovery.ps1 -Prod` 通过，报告中 `success=true`、`cleanup_ok=true`。
- [ ] 保存发布前 backend/frontend 回滚镜像标签与数据库备份路径。
- [ ] 完成 MySQL、Redis、Qdrant、backend 单故障演练，记录发现时间、恢复时间与严格复验结果。
- [ ] 回滚负责人、触发条件、镜像标签、数据库恢复点和操作窗口已确认。

完整命令与演练记录模板见 `docs/OPERATIONS_RUNBOOK.md`。
