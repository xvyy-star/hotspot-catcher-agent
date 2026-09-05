# src 目录说明

这里后续放热点捕手 Agent 的代码。

建议实现顺序：

1. `models.py`：定义统一数据模型，例如 HotspotItem、HotspotEvent、DailyBriefing。
2. `connectors/base.py`：定义所有平台采集器的统一接口。
3. `connectors/weibo.py`：实现微博热点采集器。
4. `connectors/zhihu.py`：实现知乎热点采集器。
5. `pipeline/normalize.py`：清洗标题、统一字段。
6. `pipeline/deduplicate.py`：跨平台去重。
7. `pipeline/scoring.py`：热度评分。
8. `pipeline/llm_analysis.py`：调用大模型做摘要、分类、观点分析。
9. `pipeline/briefing.py`：生成 Markdown 今日早报。
10. `push/webhook.py`：推送到现有项目。

代码原则：

- 多写“为什么这么做”的注释。
- 所有外部请求都要设置 timeout。
- 所有平台失败都不能让整个任务崩溃。
- LLM 输出必须做 JSON 校验。
- 采集、分析、推送都要记录日志。
