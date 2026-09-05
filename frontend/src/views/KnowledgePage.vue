<template>
  <section class="knowledge-page">
    <!-- 顶部四联指标看板 -->
    <div class="knowledge-metrics-grid">
      <div class="card metric-stat-card">
        <div class="stat-icon-box"><BookOpen class="stat-icon" /></div>
        <div class="stat-content">
          <span class="stat-label">已入库文档</span>
          <div class="stat-value-row">
            <span class="stat-number">{{ docs.length }}</span>
            <span class="stat-unit">篇</span>
          </div>
          <span class="stat-hint">支持早报与自定义资料</span>
        </div>
      </div>

      <div class="card metric-stat-card">
        <div class="stat-icon-box cyan"><Layers class="stat-icon" /></div>
        <div class="stat-content">
          <span class="stat-label">向量切片总量 (Chunks)</span>
          <div class="stat-value-row">
            <span class="stat-number">{{ totalChunksCount }}</span>
            <span class="stat-unit">个</span>
          </div>
          <span class="stat-hint">Qdrant 点集: {{ qdrantInfo.pointsCount ?? '-' }}</span>
        </div>
      </div>

      <div class="card metric-stat-card">
        <div class="stat-icon-box purple"><Cpu class="stat-icon" /></div>
        <div class="stat-content">
          <span class="stat-label">向量底座规格</span>
          <div class="stat-value-row">
            <span class="stat-number">{{ qdrantInfo.vectorSize || embeddingTestResult?.dimension || 1024 }}</span>
            <span class="stat-unit">维</span>
          </div>
          <span class="stat-hint font-mono">{{ qdrantInfo.collection || 'hotspot_knowledge_chunks_v2' }}</span>
        </div>
      </div>

      <div class="card metric-stat-card">
        <div class="stat-icon-box green"><CheckCircle2 class="stat-icon" /></div>
        <div class="stat-content">
          <span class="stat-label">知识库引擎状态</span>
          <div class="stat-value-row">
            <span class="status-badge" :class="knowledgeHealth?.ok ? 'status-ok' : 'status-warn'">
              <span class="status-dot"></span>
              {{ statusLabel(knowledgeHealth?.status) }}
            </span>
          </div>
          <span class="stat-hint">混合检索与带引用生成正常</span>
        </div>
      </div>
    </div>

    <!-- Tab 导航栏 -->
    <div class="knowledge-tabs-nav">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="knowledge-tab-btn"
        :class="{ active: currentTab === tab.key }"
        @click="currentTab = tab.key"
      >
        <component :is="tab.icon" class="tab-btn-icon" />
        <span>{{ tab.label }}</span>
        <span v-if="tab.badge !== undefined" class="tab-badge">{{ tab.badge }}</span>
      </button>
    </div>

    <!-- Tab 1: 📚 文档管理与入库 (默认主视图) -->
    <div v-show="currentTab === 'docs'" class="tab-content-pane">
      <!-- 录入新文档折叠展开卡片 -->
      <Transition name="fade-slide">
        <div v-if="showNewDocForm" class="card panel new-doc-drawer">
          <div class="drawer-header">
            <div class="drawer-titles">
              <h4>录入知识库新文档</h4>
              <p>文档将被自动切分成向量块并存入 Qdrant 向量库</p>
            </div>
            <button class="ghost-btn small-btn" type="button" @click="showNewDocForm = false">
              <X class="btn-icon" /> 取消录入
            </button>
          </div>

          <form class="clean-form" @submit.prevent="handleCreateDoc">
            <div class="form-grid-3">
              <div class="form-group">
                <label class="form-label">文档标题</label>
                <input
                  v-model="newDoc.title"
                  type="text"
                  placeholder="例如：2026-07-16 AI 情报分析"
                  required
                  class="input-control"
                />
              </div>
              <div class="form-group">
                <label class="form-label">来源标识 (Source)</label>
                <input
                  v-model="newDoc.source"
                  type="text"
                  placeholder="manual / daily_briefing"
                  class="input-control font-mono"
                />
              </div>
              <div class="form-group">
                <label class="form-label">标签 (逗号分隔)</label>
                <input
                  v-model="newDocTags"
                  type="text"
                  placeholder="AI, 产品情报, 技术趋势"
                  class="input-control"
                />
              </div>
            </div>

            <div class="form-grid-2">
              <div class="form-group">
                <label class="form-label">切片大小 (Chunk Size: 200~1500)</label>
                <input
                  v-model.number="newDoc.chunk_size"
                  type="number"
                  min="200"
                  max="1500"
                  class="input-control"
                />
                <span class="form-hint">单块切片字符容量，推荐 500~800 字符</span>
              </div>
              <div class="form-group">
                <label class="form-label">切片重叠长度 (Overlap: 0~500)</label>
                <input
                  v-model.number="newDoc.overlap"
                  type="number"
                  min="0"
                  max="500"
                  class="input-control"
                />
                <span class="form-hint">相邻切片上下文重叠跨度，推荐 80~120 字符</span>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">文档正文内容</label>
              <textarea
                v-model="newDoc.content"
                rows="7"
                placeholder="粘贴待入库的早报正文、行业研报、产品手册或资讯文章..."
                required
                class="textarea-control"
              ></textarea>
            </div>

            <div class="drawer-actions">
              <button class="ghost-btn small-btn" type="button" @click="showNewDocForm = false">取消</button>
              <button class="primary-btn small-btn" type="submit" :disabled="knowledgeBusy || !newDoc.content.trim()">
                <Plus class="btn-icon" /> {{ knowledgeBusy ? '切分入库中...' : '确认切分并入库' }}
              </button>
            </div>
          </form>
        </div>
      </Transition>

      <!-- 文档列表卡片 -->
      <div class="card panel">
        <!-- 列表顶部工具栏 -->
        <div class="table-toolbar">
          <div class="toolbar-left">
            <div class="search-input-wrap">
              <Search class="search-icon" />
              <input
                v-model="filterKeyword"
                type="text"
                placeholder="在已入库文档中搜索标题或标签..."
                class="filter-input"
              />
            </div>
            <span class="docs-count-pill">共 {{ filteredDocs.length }} 篇文档</span>
          </div>

          <div class="toolbar-right">
            <button
              class="ghost-btn small-btn"
              type="button"
              :disabled="knowledgeBusy"
              @click="handleIngestLatest"
            >
              <Lightbulb class="btn-icon" /> 导入最新早报
            </button>
            <button
              class="primary-btn small-btn"
              type="button"
              @click="showNewDocForm = !showNewDocForm"
            >
              <Plus class="btn-icon" /> {{ showNewDocForm ? '收起录入' : '录入新文档' }}
            </button>
          </div>
        </div>

        <!-- 表格呈现 -->
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 32%;">文档标题</th>
                <th style="width: 15%;">来源渠道</th>
                <th style="width: 18%;">主题标签</th>
                <th style="width: 10%;">分块数</th>
                <th style="width: 10%;">状态</th>
                <th style="width: 15%;">入库时间</th>
                <th style="width: 80px; text-align: center;">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in filteredDocs" :key="doc.id">
                <td class="title-cell">
                  <div class="doc-title-row">
                    <FileText class="doc-row-icon" />
                    <b>{{ doc.title }}</b>
                  </div>
                </td>
                <td>
                  <span class="source-tag font-mono">{{ doc.source || 'manual' }}</span>
                </td>
                <td>
                  <div class="tags-cluster">
                    <span v-for="tag in doc.tags || []" :key="tag" class="small-tag">{{ tag }}</span>
                    <span v-if="!doc.tags?.length" class="muted-text">-</span>
                  </div>
                </td>
                <td>
                  <span class="chunk-badge">{{ doc.chunk_count }} Chunks</span>
                </td>
                <td>
                  <span :class="['badge', doc.status === 'READY' ? 'low' : 'medium']">
                    {{ statusLabel(doc.status) }}
                  </span>
                </td>
                <td class="font-mono">{{ formatDateTime(doc.created_at) }}</td>
                <td style="text-align: center;">
                  <button
                    class="ghost-btn small-btn danger-hover-btn"
                    type="button"
                    title="删除该文档及向量分块"
                    @click="handleDeleteDoc(doc.id)"
                  >
                    <Trash2 class="btn-icon" /> 删除
                  </button>
                </td>
              </tr>
              <tr v-if="!filteredDocs.length">
                <td colspan="7" class="empty-cell">
                  <div class="empty-placeholder">
                    <BookOpen class="empty-icon" />
                    <p>{{ filterKeyword ? '未找到符合条件的文档' : '暂无入库知识库文档，点击右上角快速导入或新建' }}</p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Tab 2: 🎯 命中召回测试 (专业 RAG 沙箱) -->
    <div v-show="currentTab === 'search'" class="tab-content-pane">
      <div class="card panel">
        <div class="panel-head small">
          <div class="panel-head-titles">
            <h4>命中召回与引用测试</h4>
            <p>输入测试查询词，实时测试 Qdrant 向量检索命中切片与大模型 RAG 生成能力</p>
          </div>
        </div>

        <div class="sandbox-search-form">
          <div class="form-group">
            <textarea
              v-model="question"
              rows="3"
              placeholder="输入待测试的提问或检索词，例如：最近 AI Agent 在垂直行业有哪些最新落地趋势？"
              class="textarea-control"
            ></textarea>
          </div>

          <div class="sandbox-controls-row">
            <div class="controls-left">
              <label class="param-label">
                <span>Top-K 召回条数:</span>
                <input
                  v-model.number="topK"
                  type="number"
                  min="1"
                  max="20"
                  class="topk-input"
                />
              </label>
            </div>

            <div class="controls-right">
              <button
                class="ghost-btn small-btn"
                type="button"
                :disabled="knowledgeBusy"
                @click="handleSearch"
              >
                <Search class="btn-icon" /> 向量相似度检索
              </button>
              <button
                class="primary-btn small-btn"
                type="button"
                :disabled="knowledgeBusy"
                @click="handleAsk"
              >
                <Sparkles class="btn-icon" /> RAG 综合问答
              </button>
            </div>
          </div>
        </div>

        <!-- RAG 回答呈现 -->
        <div v-if="answer" class="rag-answer-box">
          <div class="answer-header">
            <div class="answer-title-group">
              <Sparkles class="sparkle-icon" />
              <b>智能体生成回答</b>
            </div>
            <span class="answer-meta-tag">
              模式: {{ answerModeLabel(answer.mode) }} {{ answer.model ? `· ${answer.model}` : '' }}
            </span>
          </div>
          <div class="answer-content font-readable">{{ answer.answer }}</div>
        </div>

        <!-- 召回分块列表 -->
        <div v-if="searchResults.length" class="search-results-container">
          <div class="results-header">
            <h5>召回相关分块 (共 {{ searchResults.length }} 条命中)</h5>
          </div>

          <div class="chunks-grid">
            <div
              v-for="result in searchResults"
              :key="`${result.document_id}-${result.chunk_id}`"
              class="chunk-card"
            >
              <div class="chunk-card-head">
                <div class="chunk-title">
                  <FileText class="chunk-icon" />
                  <b>{{ result.document_title }}</b>
                  <span class="chunk-idx-tag">#Chunk {{ result.chunk_index }}</span>
                </div>
                <div class="score-pill">
                  <span class="score-label">相似度:</span>
                  <span class="score-num font-mono">{{ formatNumber(result.score) }}</span>
                </div>
              </div>

              <div class="chunk-meta">
                <span>来源: {{ result.source || '手动录入' }}</span>
              </div>

              <div class="chunk-text">
                {{ shortText(result.content, 260) }}
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="!answer" class="sandbox-empty-prompt">
          <Search class="prompt-icon" />
          <p>输入提问并点击“向量相似度检索”或“RAG 综合问答”，在此查看精准切片命中与相似度得分</p>
        </div>
      </div>
    </div>

    <!-- Tab 3: ⚙️ 向量底座与 RAG 运维 -->
    <div v-show="currentTab === 'ops'" class="tab-content-pane">
      <!-- 运维规格与测试 -->
      <div class="card panel">
        <div class="panel-head small">
          <div class="panel-head-titles">
            <h4>Embedding 模型测试与 Qdrant 底座</h4>
            <p>测试向量生成通道连通性、查看集合状态与延迟指标</p>
          </div>
          <button class="ghost-btn small-btn" type="button" @click="loadKnowledgePage">
            <RefreshCw class="btn-icon" /> 刷新底座状态
          </button>
        </div>

        <div class="embedding-test-action-bar">
          <button
            class="primary-btn small-btn"
            type="button"
            :disabled="knowledgeBusy"
            @click="handleTestEmbedding"
          >
            <Wifi class="btn-icon" /> 测试当前 Embedding 连通性
          </button>
          <span class="test-tip">将向配置的向量模型发送测试文本并校验输出向量维度</span>
        </div>

        <!-- 测试结果卡片 -->
        <div v-if="embeddingTestResult" class="embedding-test-result-box" :class="{ ok: embeddingTestResult.ok }">
          <div class="result-title">
            <component :is="embeddingTestResult.ok ? CheckCircle2 : AlertTriangle" class="result-icon" />
            <b>{{ embeddingTestResult.ok ? 'Embedding 通道工作正常' : 'Embedding 测试失败' }}</b>
          </div>
          <div class="result-details font-mono">
            <span>供应商: {{ embeddingTestResult.provider }}</span>
            <span>模型: {{ embeddingTestResult.model }}</span>
            <span>向量维度: {{ embeddingTestResult.dimension }} 维</span>
            <span>响应延迟: {{ embeddingTestResult.latency_ms }} ms</span>
          </div>
          <div v-if="embeddingTestResult.fallback" class="fallback-warning">
            触发兜底策略: {{ embeddingTestResult.error_message || '未知' }}
          </div>
        </div>
      </div>

      <!-- 重建向量表单卡片 -->
      <div class="card panel">
        <div class="panel-head small">
          <div class="panel-head-titles">
            <h4>异步重建向量索引 (Re-index)</h4>
            <p>在更换 Embedding 模型或更新切片策略后，后台异步重新切分与向量化</p>
          </div>
        </div>

        <div class="clean-form">
          <div class="form-grid-3">
            <div class="form-group">
              <label class="form-label">目标文档 ID (留空表示全量重建)</label>
              <input
                v-model="reindexDocumentId"
                type="text"
                placeholder="留空=全部文档，或填数字如 1"
                class="input-control font-mono"
              />
            </div>
            <div class="form-group">
              <label class="form-label">处理批大小 (Batch Size: 1~64)</label>
              <input
                v-model.number="reindexBatchSize"
                type="number"
                min="1"
                max="64"
                class="input-control"
              />
            </div>
            <div class="form-group flex-center-group">
              <label class="checkbox-control">
                <input v-model="reindexRecreateCollection" type="checkbox" />
                <span>同时清空并重建 Qdrant Collection</span>
              </label>
            </div>
          </div>

          <div class="form-actions-right">
            <button
              class="primary-btn small-btn"
              type="button"
              :disabled="knowledgeBusy"
              @click="handleReindexVectors"
            >
              <DatabaseZap class="btn-icon" /> 启动异步重建任务
            </button>
          </div>
        </div>
      </div>

      <!-- 异步任务历史表格卡片 -->
      <div class="card panel">
        <div class="panel-head small">
          <div class="panel-head-titles">
            <h4>任务执行历史记录</h4>
            <p>记录所有知识库导入与向量重建的异步执行状态及耗时</p>
          </div>
          <button class="ghost-btn small-btn" type="button" @click="loadKnowledgePage">
            <RefreshCw class="btn-icon" /> 刷新任务
          </button>
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 80px;">任务</th>
                <th style="width: 100px;">状态</th>
                <th>文档对象</th>
                <th style="width: 90px;">分块数</th>
                <th>向量模型</th>
                <th>集合名</th>
                <th style="width: 100px;">耗时</th>
                <th>异常信息</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="run in ingestRuns" :key="run.id">
                <td class="font-mono">#{{ run.id }}</td>
                <td><span :class="['badge', statusBadgeClass(run.status)]">{{ statusLabel(run.status) }}</span></td>
                <td class="title-cell"><b>{{ run.document_title || run.document_id || '全量文档重建' }}</b></td>
                <td class="font-mono">{{ run.chunk_count }}</td>
                <td class="font-mono">{{ run.embedding_model || '-' }}</td>
                <td class="font-mono">{{ run.vector_collection || '-' }}</td>
                <td class="font-mono">{{ formatDuration(run.duration_ms) }}</td>
                <td class="error-cell">{{ run.error_message || '-' }}</td>
              </tr>
              <tr v-if="!ingestRuns.length">
                <td colspan="8" class="empty-cell">暂无异步导入或重建任务</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Cpu,
  DatabaseZap,
  FileText,
  Layers,
  Lightbulb,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Wifi,
  X,
} from 'lucide-vue-next'

import {
  askKnowledge,
  createKnowledgeDocument,
  deleteKnowledgeDocument,
  getKnowledgeHealth,
  ingestLatestBriefingToKnowledge,
  listKnowledgeDocuments,
  listKnowledgeIngestRuns,
  reindexKnowledgeVectorsAsync,
  searchKnowledge,
  testKnowledgeEmbedding,
} from '@/api/hotspot'
import type {
  KnowledgeAskResult,
  KnowledgeDocument,
  KnowledgeEmbeddingTestResult,
  KnowledgeIngestRun,
  KnowledgeSearchResult,
} from '@/types/hotspot'

const emit = defineEmits<{
  (e: 'message', text: string): void
  (e: 'error', err: any): void
  (e: 'set-loading', loading: boolean): void
}>()

// Tab 配置
type TabKey = 'docs' | 'search' | 'ops'
const currentTab = ref<TabKey>('docs')

const knowledgeHealth = ref<Record<string, any> | null>(null)
const docs = ref<KnowledgeDocument[]>([])
const ingestRuns = ref<KnowledgeIngestRun[]>([])
const searchResults = ref<KnowledgeSearchResult[]>([])
const answer = ref<KnowledgeAskResult | null>(null)
const embeddingTestResult = ref<KnowledgeEmbeddingTestResult | null>(null)

// 页面控制
const showNewDocForm = ref(false)
const filterKeyword = ref('')
const question = ref('')
const topK = ref(5)
const reindexBatchSize = ref(16)
const reindexDocumentId = ref('')
const reindexRecreateCollection = ref(false)
const newDocTags = ref('AI, 产品情报, 技术趋势')
const newDoc = ref({ title: '', content: '', source: 'manual', chunk_size: 700, overlap: 100 })
const knowledgeBusy = ref(false)

const tabs = computed(() => [
  { key: 'docs' as TabKey, label: '文档管理与入库', icon: BookOpen, badge: docs.value.length },
  { key: 'search' as TabKey, label: '命中召回测试', icon: Search },
  { key: 'ops' as TabKey, label: '向量底座与 RAG 运维', icon: Cpu },
])

// 统计切片总数
const totalChunksCount = computed(() => {
  return docs.value.reduce((acc, doc) => acc + (doc.chunk_count || 0), 0)
})

// 过滤后的文档列表
const filteredDocs = computed(() => {
  const kw = filterKeyword.value.trim().toLowerCase()
  if (!kw) return docs.value
  return docs.value.filter((doc) => {
    const titleMatch = doc.title?.toLowerCase().includes(kw)
    const sourceMatch = doc.source?.toLowerCase().includes(kw)
    const tagMatch = doc.tags?.some((t) => t.toLowerCase().includes(kw))
    return titleMatch || sourceMatch || tagMatch
  })
})

const qdrantInfo = computed(() => {
  const result = knowledgeHealth.value?.data?.result
  const vectorConfig = result?.config?.params?.vectors
  return {
    collection: knowledgeHealth.value?.collection || '-',
    vectorSize: vectorConfig?.size,
    pointsCount: result?.points_count,
  }
})

async function runTask(task: () => Promise<void>) {
  emit('set-loading', true)
  try {
    await task()
  } catch (error) {
    emit('error', error)
  } finally {
    emit('set-loading', false)
  }
}

async function loadKnowledgePage() {
  await runTask(async () => {
    const [health, rows, runRows] = await Promise.allSettled([
      getKnowledgeHealth(),
      listKnowledgeDocuments(100),
      listKnowledgeIngestRuns({ limit: 20 }),
    ])
    if (health.status === 'fulfilled') knowledgeHealth.value = health.value
    if (rows.status === 'fulfilled') docs.value = rows.value
    if (runRows.status === 'fulfilled') ingestRuns.value = runRows.value
  })
}

async function handleCreateDoc() {
  if (!newDoc.value.title.trim() || !newDoc.value.content.trim()) return
  knowledgeBusy.value = true
  try {
    const tags = newDocTags.value.split(',').map((item) => item.trim()).filter(Boolean)
    const result = await createKnowledgeDocument({ ...newDoc.value, tags })
    const doc = result.document || result
    emit('message', `知识库导入成功：${doc.title}，共切分 ${doc.chunk_count} 个分块`)
    newDoc.value = { ...newDoc.value, title: '', content: '' }
    showNewDocForm.value = false
    await loadKnowledgePage()
  } catch (error) {
    emit('error', error)
  } finally {
    knowledgeBusy.value = false
  }
}

async function handleIngestLatest() {
  knowledgeBusy.value = true
  try {
    const result = await ingestLatestBriefingToKnowledge()
    const doc = result.document || result
    emit('message', `最新早报已写入知识库：${doc.title || '知识库文档'}`)
    await loadKnowledgePage()
  } catch (error) {
    emit('error', error)
  } finally {
    knowledgeBusy.value = false
  }
}

async function handleSearch() {
  if (!question.value.trim()) return emit('error', '请先输入检索词或测试问题')
  knowledgeBusy.value = true
  try {
    answer.value = null
    searchResults.value = await searchKnowledge(question.value, topK.value)
    if (!searchResults.value.length) {
      emit('message', '未检索到相关切片，可尝试修改提问或检查知识库')
    }
  } catch (error) {
    emit('error', error)
  } finally {
    knowledgeBusy.value = false
  }
}

async function handleAsk() {
  if (!question.value.trim()) return emit('error', '请先输入测试问题')
  knowledgeBusy.value = true
  try {
    const result = await askKnowledge(question.value, topK.value)
    answer.value = result
    searchResults.value = result.references || []
  } catch (error) {
    emit('error', error)
  } finally {
    knowledgeBusy.value = false
  }
}

async function handleDeleteDoc(id: number) {
  if (!window.confirm('确认删除这个知识库文档及其所有向量分块？')) return
  await runTask(async () => {
    await deleteKnowledgeDocument(id)
    emit('message', '知识库文档已删除')
    await loadKnowledgePage()
  })
}

async function handleTestEmbedding() {
  knowledgeBusy.value = true
  try {
    embeddingTestResult.value = await testKnowledgeEmbedding(
      question.value.trim() || 'AI Agent 热点捕手 RAG 向量模型连通性测试',
    )
    if (embeddingTestResult.value.ok) {
      emit('message', `Embedding 正常：${embeddingTestResult.value.model}，${embeddingTestResult.value.dimension} 维`)
    } else {
      emit('error', `Embedding 测试失败：${embeddingTestResult.value.error_message || '未知错误'}`)
    }
  } catch (error) {
    emit('error', error)
  } finally {
    knowledgeBusy.value = false
  }
}

async function handleReindexVectors() {
  const docIdText = String(reindexDocumentId.value || '').trim()
  const documentId = docIdText ? Number(docIdText) : undefined
  if (docIdText && (!Number.isInteger(documentId) || Number(documentId) <= 0)) {
    return emit('error', '文档 ID 必须是正整数，或留空表示全量重建')
  }
  const confirmText = reindexRecreateCollection.value
    ? '确认清空并重建 Qdrant Collection，重新写入全部向量？'
    : '确认按当前 Embedding 配置异步重建知识库向量？'
  if (!window.confirm(confirmText)) return

  knowledgeBusy.value = true
  try {
    const run = await reindexKnowledgeVectorsAsync({
      document_id: documentId,
      batch_size: reindexBatchSize.value,
      recreate_collection: reindexRecreateCollection.value,
    })
    emit('message', `向量重建任务已创建：run #${run.id}`)
    await loadKnowledgePage()
  } catch (error) {
    emit('error', error)
  } finally {
    knowledgeBusy.value = false
  }
}

onMounted(loadKnowledgePage)

defineExpose({
  refresh: loadKnowledgePage,
})

function statusBadgeClass(status?: string): string {
  if (status === 'SUCCESS' || status === 'ACTIVE') return 'low'
  if (status === 'FAILED' || status === 'ERROR') return 'high'
  return 'medium'
}

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    OK: '正常',
    READY: '就绪',
    ACTIVE: '已启用',
    SUCCESS: '成功',
    QUEUED: '排队中',
    PENDING: '等待中',
    PARSING: '解析中',
    CHUNKING: '分块中',
    EMBEDDING: '向量化中',
    VECTOR_UPSERT: '写入向量库',
    RUNNING: '运行中',
    FAILED: '失败',
    ERROR: '异常',
    UNKNOWN: '就绪',
  }
  return labels[String(status || 'UNKNOWN').toUpperCase()] || status || '就绪'
}

function answerModeLabel(mode?: string): string {
  const labels: Record<string, string> = {
    LLM_RAG: '知识库引用增强',
    RULE_RAG: '规则摘要',
    NO_CONTEXT: '未检索到资料',
    DIRECT_REPLY: '直接回答',
  }
  return labels[String(mode || '').toUpperCase()] || mode || '知识库增强'
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = dayjs(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm:ss') : value
}

function formatNumber(value?: number): string {
  const num = Number(value || 0)
  return num.toFixed(3)
}

function formatDuration(value?: number): string {
  if (value === undefined || value === null) return '-'
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(1)}s`
}

function shortText(text: string, max = 180): string {
  return !text ? '-' : text.length > max ? `${text.slice(0, max)}...` : text
}
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

/* 顶部四联统计卡 */
.knowledge-metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.metric-stat-card {
  padding: 16px 18px;
  display: flex;
  gap: 14px;
  align-items: center;
}

.stat-icon-box {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(0, 242, 254, 0.12);
  color: var(--color-primary);
  flex-shrink: 0;
}

.stat-icon-box.cyan {
  background: rgba(6, 182, 212, 0.12);
  color: #06b6d4;
}

.stat-icon-box.purple {
  background: rgba(168, 85, 247, 0.12);
  color: #a855f7;
}

.stat-icon-box.green {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.stat-icon {
  width: 20px;
  height: 20px;
}

.stat-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.stat-label {
  font-size: 12px;
  color: var(--color-muted);
}

.stat-value-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.stat-number {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: normal !important;
}

.stat-unit {
  font-size: 12px;
  color: var(--color-muted);
}

.stat-hint {
  font-size: 11px;
  color: var(--color-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 状态 Badge */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.status-ok {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.status-badge.status-warn {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

/* Tab 导航 */
.knowledge-tabs-nav {
  display: flex;
  gap: 8px;
  padding: 4px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow-x: auto;
}

.knowledge-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  border: none;
  background: transparent;
  color: var(--color-muted);
  font-size: 13px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.knowledge-tab-btn:hover {
  color: var(--color-text);
  background: var(--surface-subtle);
}

.knowledge-tab-btn.active {
  color: var(--color-primary);
  background: var(--surface-subtle);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

.tab-btn-icon {
  width: 16px;
  height: 16px;
}

.tab-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  background: rgba(0, 242, 254, 0.15);
  color: var(--color-primary);
}

/* 标签页内容 */
.tab-content-pane {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 新建文档抽屉 */
.new-doc-drawer {
  padding: 20px 22px;
  border-left: 3px solid var(--color-primary);
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-subtle);
}

.drawer-titles h4 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.drawer-titles p {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted);
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
}

/* 工具栏 */
.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  max-width: 460px;
}

.search-input-wrap {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 12px;
  width: 15px;
  height: 15px;
  color: var(--color-muted);
}

.filter-input {
  width: 100%;
  min-height: 36px;
  padding: 0 12px 0 34px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-subtle);
  color: var(--color-text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s ease;
}

.filter-input:focus {
  border-color: var(--color-primary);
}

.docs-count-pill {
  font-size: 12px;
  color: var(--color-muted);
  white-space: nowrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 表格内元素 */
.doc-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-row-icon {
  width: 16px;
  height: 16px;
  color: var(--color-primary);
  flex-shrink: 0;
}

.source-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface-subtle);
  color: var(--color-muted);
  border: 1px solid var(--border-subtle);
}

.tags-cluster {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.small-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(0, 242, 254, 0.08);
  color: var(--color-primary);
}

.chunk-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text);
}

.danger-hover-btn:hover {
  color: #f43f5e;
  border-color: rgba(244, 63, 94, 0.3);
  background: rgba(244, 63, 94, 0.08);
}

.empty-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 30px 10px;
  color: var(--color-muted);
}

.empty-icon {
  width: 32px;
  height: 32px;
  opacity: 0.5;
}

/* 表单结构 */
.clean-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group.flex-center-group {
  justify-content: flex-end;
  padding-bottom: 6px;
}

.form-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.input-control {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-subtle);
  color: var(--color-text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s ease;
}

.input-control:focus,
.textarea-control:focus {
  border-color: var(--color-primary);
}

.textarea-control {
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-subtle);
  color: var(--color-text);
  font-size: 13px;
  line-height: 1.6;
  outline: none;
  resize: vertical;
  transition: border-color 0.2s ease;
}

.form-hint {
  font-size: 11px;
  color: var(--color-muted);
}

.checkbox-control {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text);
  cursor: pointer;
}

.checkbox-control input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
}

/* 召回测试沙箱 */
.sandbox-search-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 20px;
  background: var(--surface-subtle);
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  margin-bottom: 16px;
}

.sandbox-controls-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.param-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-muted);
}

.topk-input {
  width: 60px;
  min-height: 32px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-card);
  color: var(--color-text);
  font-size: 13px;
  text-align: center;
}

.controls-right {
  display: flex;
  gap: 10px;
}

/* RAG 回答卡片 */
.rag-answer-box {
  padding: 18px 20px;
  border-radius: 10px;
  background: rgba(0, 242, 254, 0.05);
  border: 1px solid rgba(0, 242, 254, 0.2);
  margin-bottom: 16px;
}

.answer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.answer-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-primary);
  font-size: 14px;
}

.sparkle-icon {
  width: 18px;
  height: 18px;
}

.answer-meta-tag {
  font-size: 11px;
  color: var(--color-muted);
}

.answer-content {
  font-size: 14px;
  color: var(--color-text);
  line-height: 1.7;
  white-space: pre-wrap;
}

/* 召回分块卡片网格 */
.search-results-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.results-header h5 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.chunks-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.chunk-card {
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chunk-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.chunk-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text);
}

.chunk-icon {
  width: 14px;
  height: 14px;
  color: var(--color-primary);
}

.chunk-idx-tag {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-card);
  color: var(--color-muted);
}

.score-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.chunk-meta {
  font-size: 11px;
  color: var(--color-muted);
}

.chunk-text {
  font-size: 12px;
  color: var(--color-text);
  line-height: 1.6;
  background: var(--surface-card);
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}

.sandbox-empty-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 36px 12px;
  color: var(--color-muted);
  text-align: center;
}

.prompt-icon {
  width: 32px;
  height: 32px;
  opacity: 0.4;
}

/* 运维 Tab */
.embedding-test-action-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.test-tip {
  font-size: 12px;
  color: var(--color-muted);
}

.embedding-test-result-box {
  padding: 14px 16px;
  border-radius: 8px;
  background: rgba(244, 63, 94, 0.08);
  border: 1px solid rgba(244, 63, 94, 0.2);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.embedding-test-result-box.ok {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.2);
}

.result-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text);
}

.result-icon {
  width: 16px;
  height: 16px;
}

.result-details {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: var(--color-muted);
}

.fallback-warning {
  font-size: 12px;
  color: #f59e0b;
}

.form-actions-right {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
}

.btn-icon {
  width: 15px;
  height: 15px;
}

/* 响应式 */
@media (max-width: 1100px) {
  .knowledge-metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .form-grid-3 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chunks-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .knowledge-metrics-grid {
    grid-template-columns: 1fr;
  }

  .form-grid-3,
  .form-grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
