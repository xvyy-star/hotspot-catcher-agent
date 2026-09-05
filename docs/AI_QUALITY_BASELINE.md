# AI 质量基线与回归评测

项目提供不依赖 MySQL、Redis、Qdrant 或在线模型的固定评测集，用于阻止分类、排序、摘要事实和引用质量静默下降。

## 一键运行

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ai_quality.py
```

脚本会把完整 JSON 写入 `reports/ai_quality_latest.json`，同时输出到标准输出。全部门槛通过时退出码为 `0`，任一门槛失败或输入格式错误时退出码为 `1`，可以直接作为 CI gate。

固定数据集位于 `backend/tests/fixtures/ai_quality_baseline.json`，包含：

- 7 条分类 golden cases，覆盖 AI、大模型、开源、科技产品、社会民生、财经商业、政策监管与来源强提示。
- 3 组排序 cases，覆盖多源确认、行业相关度和可观测热度。
- 2 条摘要与引用 cases，覆盖关键事实、空摘要、无依据数字/已知错误断言、原文 URL 和 RAG 文档块引用。

报告记录数据集版本和 SHA-256，修改 golden set 后报告可以明确识别基线变化。

## 质量门槛

| 指标 | 门槛 | 含义 |
| --- | ---: | --- |
| `classification_accuracy` | `>= 0.90` | 分类 golden accuracy |
| `ranking_pairwise_accuracy` | `>= 1.00` | 期望排序中所有事件对的相对顺序正确 |
| `summary_fact_coverage` | `>= 1.00` | 摘要必须覆盖 fixture 指定的核心事实 |
| `citation_coverage` | `>= 1.00` | 早报必须保留指定原文 URL 与 RAG 引用标识 |
| `summary_nonempty_rate` | `>= 1.00` | 不允许空摘要进入早报 |
| `unsupported_claim_rate` | `<= 0.00` | 不允许命中已知错误断言或新增无来源数字 |

分类采用行业评测常用的 90% 准确率门槛；排序、事实、引用和无依据断言属于确定性业务约束，因此采用严格门槛。当前分类集只有 7 条，任意一条失败仍会触发门槛，后续扩充到 10 条以上后才会体现 90% 的容错空间。

## 评测已捕获的模型输出

线上模型具有概率性，不应在每次单元测试中直接请求外部 API。模型或 Prompt 变更时，先用同一 fixture 生成完整 prediction snapshot，再运行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ai_quality.py `
  --predictions reports\candidate_model_predictions.json `
  --output reports\candidate_model_quality.json
```

Prediction snapshot 格式：

```json
{
  "dataset_version": "2026-07-16.1",
  "classification": {
    "class-ai-model": "AI / 大模型"
  },
  "generation": {
    "summary-multisource-agent-sdk": {
      "summary": "OpenAI 发布 Agent SDK 2.0。"
    }
  }
}
```

实际文件必须包含数据集中所有 classification 和 generation case。数据集版本不一致、case 缺失或摘要为空都会失败关闭，避免用不完整样本得到虚高分数。排序继续调用项目当前确定性评分器，以便同时发现代码回归。

## 维护规则

1. 线上出现典型误分类、错序、事实错误或丢引用时，先匿名化后追加为新的 fixture case。
2. 更新数据集时递增 `dataset.version`，同步更新 prediction snapshot。
3. 不因某次回归失败直接下调事实或引用门槛；先修实现或确认 golden expectation 是否错误。
4. Prompt、Provider、模型版本或评分权重变更后，运行完整 pytest 和本评测脚本并保留 JSON 报告。
