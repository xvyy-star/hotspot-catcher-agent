<template>
  <div class="card panel">
    <div class="panel-head">
      <div class="panel-head-left">
        <div class="panel-title-row">
          <h2>热点事件</h2>
          <span class="count-badge">共 {{ filteredEvents.length }} 条事件</span>
        </div>
        <p>只展示已通过真实数据闸门的事件：必须有 item 级原文链接，样例/模拟/无出处数据不展示。</p>
      </div>
      <div class="top-actions">
        <div class="search-input-wrap">
          <Search class="search-icon" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索事件标题 / 摘要 / 来源..."
            class="table-search-input"
          />
          <button v-if="searchQuery" class="clear-search-btn" type="button" title="清空搜索" @click="searchQuery = ''">✕</button>
        </div>
        <ChromeSelect
          :modelValue="categoryFilter"
          :options="categoryOptions"
          @update:modelValue="$emit('update:categoryFilter', $event as string)"
        />
        <ChromeSelect
          :modelValue="riskFilter"
          :options="riskOptions"
          @update:modelValue="$emit('update:riskFilter', $event as string)"
        />
      </div>
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>标题与摘要</th>
            <th>分类</th>
            <th>热度</th>
            <th>反馈</th>
            <th>可信度</th>
            <th>风险</th>
            <th>业务关联</th>
            <th>RAG</th>
            <th>来源</th>
            <th>分析</th>
            <th>时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="event in filteredEvents" :key="event.id || event.event_key">
            <tr :class="{ selected: expandedEventKey === eventRowKey(event) }">
              <td class="title-cell">
                <div class="title-main" :title="event.title">
                  <b>{{ event.title }}</b>
                </div>
                <div v-if="event.summary" class="title-summary-line" :title="event.summary">
                  {{ event.summary }}
                </div>
              </td>
              <td>{{ event.category || '综合' }}</td>
              <td>
                <span class="heat-val">{{ formatNumber(displayHeatScore(event)) }}</span>
                <span v-if="event.feedback?.score_adjustment" class="feedback-adj" :title="'人工校正 ' + (event.feedback.score_adjustment > 0 ? '+' : '') + event.feedback.score_adjustment">
                  {{ event.feedback.score_adjustment > 0 ? '+' : '' }}{{ event.feedback.score_adjustment }}
                </span>
              </td>
              <td>
                <div class="feedback-mini">
                  <span v-if="event.feedback?.is_favorite" class="mini-pill favorite">收藏</span>
                  <span v-if="event.feedback?.is_blocked" class="mini-pill blocked">屏蔽</span>
                  <span v-if="event.feedback?.positive_count" class="mini-pill positive">+{{ event.feedback.positive_count }}</span>
                  <span v-if="event.feedback?.negative_count" class="mini-pill negative">-{{ event.feedback.negative_count }}</span>
                  <span v-if="!event.feedback?.positive_count && !event.feedback?.negative_count && !event.feedback?.is_favorite" class="mini-pill none">-</span>
                </div>
              </td>
              <td>
                <span :class="['badge', credibilityClass(event.credibility_level)]">
                  {{ levelLabel(event.credibility_level) }} · {{ formatNumber(event.credibility_score) }}
                </span>
              </td>
              <td><span :class="['badge', riskClass(event.risk_level)]">{{ levelLabel(event.risk_level) }}</span></td>
              <td>
                <span :class="['badge', relevanceClass(event.business_relevance)]">
                  {{ businessRelevanceLabel(event.business_relevance) }}
                </span>
              </td>
              <td>
                <div class="rag-cell">
                  <span :class="['badge', ragLevelClass(event.knowledge_relevance_level)]">
                    {{ knowledgeRelevanceLabel(event.knowledge_relevance_level) }}
                  </span>
                  <span v-if="event.rag_references?.length" class="rag-count-pill" :title="`${event.rag_references.length} 条知识库引用切片`">
                    {{ event.rag_references.length }}
                  </span>
                </div>
              </td>
              <td>
                <span class="source-code-text" :title="event.source_codes?.join(', ') || '-'">
                  {{ event.source_codes?.join(', ') || '-' }}
                </span>
              </td>
              <td>{{ analysisModeLabel(event.analysis_mode) }}</td>
              <td class="time-cell">{{ formatDateTime(event.updated_at || event.created_at) }}</td>
              <td>
                <button
                  :class="['ghost-btn', 'small-btn', { active: expandedEventKey === eventRowKey(event) }]"
                  type="button"
                  @click="toggleEventDetail(event)"
                >
                  {{ expandedEventKey === eventRowKey(event) ? '收起' : '详情' }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedEventKey === eventRowKey(event)" class="event-detail-row">
              <td colspan="12">
                <div class="event-detail-panel">
                  <div class="detail-section">
                    <h3>可信度分析与来源链</h3>
                    <p>{{ event.credibility_reason || '暂无可信度评估说明。' }}</p>
                    <div class="detail-tags">
                      <span :class="['badge', credibilityClass(event.credibility_level)]">可信度评分 {{ formatNumber(event.credibility_score) }}</span>
                      <span :class="['badge', hasVerifiableEvidence(event) ? 'low' : 'high']">{{ hasVerifiableEvidence(event) ? '真实来源+原文链接' : '缺少原文证据' }}</span>
                    </div>
                  </div>

                  <div class="detail-section full-detail">
                    <h3>原文证据 ({{ evidenceItems(event).length }})</h3>
                    <ul v-if="evidenceItems(event).length" class="detail-list evidence-links">
                      <li v-for="item in evidenceItems(event)" :key="item.url">
                        <a :href="item.url" target="_blank" rel="noreferrer">{{ item.title }}</a>
                        <span> · {{ item.source_name || item.source }} · {{ item.rank ? `排名 #${item.rank}` : '榜单项' }}</span>
                      </li>
                    </ul>
                    <p v-else class="empty-hint">无 item 级原文链接，已不应进入展示列表。</p>
                  </div>

                  <div class="detail-section">
                    <h3>业务关联判断</h3>
                    <p>{{ event.business_relevance_reason || '暂无业务关联判断。' }}</p>
                    <div class="detail-tags">
                      <span class="badge ai">相关度 {{ formatNumber(event.knowledge_relevance_score) }}</span>
                      <span :class="['badge', ragLevelClass(event.knowledge_relevance_level)]">{{ knowledgeRelevanceLabel(event.knowledge_relevance_level) }}</span>
                    </div>
                  </div>

                  <div class="detail-section">
                    <h3>历史相似材料</h3>
                    <ul v-if="event.historical_insights?.length" class="detail-list">
                      <li v-for="insight in event.historical_insights" :key="insight">{{ insight }}</li>
                    </ul>
                    <p v-else class="empty-hint">暂无历史相似材料。</p>
                  </div>

                  <div class="detail-section full-detail">
                    <h3>RAG 检索切片 ({{ event.rag_references?.length || 0 }})</h3>
                    <div v-if="event.rag_references?.length" class="rag-ref-grid">
                      <article v-for="ref in event.rag_references" :key="`${ref.document_id}-${ref.chunk_id}`" class="rag-ref-card">
                        <div class="rag-ref-head">
                          <b>{{ ref.document_title }}</b>
                          <span>相关度 {{ formatNumber(ref.score) }}</span>
                        </div>
                        <p>{{ ref.preview || '暂无预览' }}</p>
                        <div class="muted-text">文档 #{{ ref.document_id }} · 分块 #{{ ref.chunk_index }} · {{ ref.source || '手动导入' }}</div>
                      </article>
                    </div>
                    <p v-else class="empty-hint">暂无 RAG 引用。</p>
                  </div>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!filteredEvents.length">
            <td colspan="12" class="empty-cell">
              {{ searchQuery ? '未找到匹配关键词的事件，请尝试更换关键词' : '暂无带原文链接的真实数据' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import dayjs from 'dayjs'
import { Search } from 'lucide-vue-next'
import ChromeSelect from '@/components/ChromeSelect.vue'
import type { HotspotEvent } from '@/types/hotspot'

const props = defineProps<{
  events: HotspotEvent[]
  categories: string[]
  categoryFilter: string
  riskFilter: string
}>()

const emit = defineEmits<{
  (e: 'update:categoryFilter', value: string): void
  (e: 'update:riskFilter', value: string): void
}>()

const searchQuery = ref('')
const expandedEventKey = ref('')

const categoryOptions = computed(() => {
  return [
    { value: '', label: '全部分类' },
    ...props.categories.map(cat => ({ value: cat, label: cat }))
  ]
})

const riskOptions = [
  { value: '', label: '全部风险' },
  { value: 'LOW', label: '低风险' },
  { value: 'MEDIUM', label: '中风险' },
  { value: 'HIGH', label: '高风险' }
]

const filteredEvents = computed(() => {
  let list = props.events || []
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((e) => {
      return (
        (e.title && e.title.toLowerCase().includes(q)) ||
        (e.summary && e.summary.toLowerCase().includes(q)) ||
        (e.category && e.category.toLowerCase().includes(q)) ||
        (e.source_codes && e.source_codes.some(s => s.toLowerCase().includes(q)))
      )
    })
  }
  return list
})

function eventRowKey(event: HotspotEvent): string {
  return String(event.id || event.event_key || event.title)
}

function toggleEventDetail(event: HotspotEvent) {
  const key = eventRowKey(event)
  expandedEventKey.value = expandedEventKey.value === key ? '' : key
}

function riskClass(risk?: string): string {
  if (risk === 'HIGH') return 'high'
  if (risk === 'MEDIUM') return 'medium'
  return 'low'
}

function credibilityClass(level?: string): string {
  if (level === 'HIGH') return 'low'
  if (level === 'MEDIUM') return 'ai'
  return 'medium'
}

function relevanceClass(level?: string): string {
  if (level === 'HIGH') return 'low'
  if (level === 'LOW') return 'medium'
  if (level === 'MEDIUM') return 'ai'
  return 'medium'
}

function ragLevelClass(level?: string): string {
  if (level === 'HIGH') return 'low'
  if (level === 'MEDIUM') return 'ai'
  if (level === 'ERROR') return 'high'
  return 'medium'
}

function levelLabel(level?: string): string {
  const labels: Record<string, string> = { HIGH: '高', MEDIUM: '中', LOW: '低' }
  return labels[String(level || 'LOW').toUpperCase()] || level || '低'
}

function businessRelevanceLabel(level?: string): string {
  if (String(level || '').toUpperCase() === 'UNKNOWN') return '待判断'
  return levelLabel(level)
}

function knowledgeRelevanceLabel(level?: string): string {
  const labels: Record<string, string> = {
    HIGH: '高相关',
    MEDIUM: '中相关',
    LOW: '低相关',
    NO_CONTEXT: '无参考',
    ERROR: '检索异常',
  }
  return labels[String(level || 'NO_CONTEXT').toUpperCase()] || level || '无参考'
}

function analysisModeLabel(mode?: string): string {
  const labels: Record<string, string> = {
    LLM: 'AI 分析',
    LLM_CACHE: 'AI 缓存',
    RULE: '规则分析',
    RULE_FALLBACK: '规则兜底',
  }
  return labels[String(mode || '').toUpperCase()] || mode || '-'
}

const fakeSourceCodes = new Set(['sample', 'demo', 'mock', 'fake', 'placeholder', 'test'])

function hasValidEvidenceUrl(url?: string): boolean {
  if (!url) return false
  try {
    const parsed = new URL(url)
    return ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.hostname)
  } catch {
    return false
  }
}

function isFakeSourceItem(item: { source?: string; raw_payload?: Record<string, any> }): boolean {
  return fakeSourceCodes.has(String(item.source || '').toLowerCase()) || Boolean(item.raw_payload?.is_fallback_sample)
}

function evidenceItems(event: HotspotEvent) {
  const seen = new Set<string>()
  return [...(event.items || [])]
    .filter((item) => {
      if (!hasValidEvidenceUrl(item.url) || isFakeSourceItem(item)) return false
      if (seen.has(item.url!)) return false
      seen.add(item.url!)
      return true
    })
    .slice(0, 8)
}

function hasVerifiableEvidence(event: HotspotEvent): boolean {
  if (event.is_fallback_sample) return false
  return evidenceItems(event).length > 0
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = dayjs(value)
  return date.isValid() ? date.format('MM-DD HH:mm') : value
}

function formatNumber(value?: number): string {
  const num = Number(value || 0)
  return Number.isInteger(num) ? String(num) : num.toFixed(2)
}

function displayHeatScore(event: HotspotEvent): number {
  const base = Number(event.heat_score || 0)
  const adjustment = Number(event.score_adjustment || event.feedback?.score_adjustment || 0)
  if (adjustment) return Math.max(0, Math.min(100, base + adjustment))
  return Math.max(0, Math.min(100, Number(event.display_heat_score || base || 0)))
}
</script>

<style scoped>
.panel-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.count-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-subtle);
  color: var(--color-primary);
  border: 1px solid var(--border-subtle);
}

.search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 10px;
  width: 14px;
  height: 14px;
  color: var(--color-muted);
  pointer-events: none;
}

.table-search-input {
  height: 32px;
  width: 220px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-card);
  color: var(--color-text);
  font-size: 12.5px;
  padding: 0 26px 0 30px;
  outline: none;
  transition: var(--transition-smooth);
}

.table-search-input:focus {
  border-color: var(--color-primary);
  width: 260px;
  box-shadow: 0 0 0 3px var(--glow-accent);
}

.clear-search-btn {
  position: absolute;
  right: 8px;
  border: none;
  background: transparent;
  color: var(--color-muted);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
}

.clear-search-btn:hover {
  color: var(--color-text);
}

.table-wrap {
  max-height: calc(100vh - 240px);
  overflow: auto;
}

.data-table {
  min-width: 1280px;
  border-collapse: collapse;
}

.data-table thead {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-card);
}

.data-table th {
  white-space: nowrap;
  font-size: 12px;
  padding: 10px 14px;
  font-weight: 700;
  color: var(--color-muted);
  border-bottom: 1px solid var(--border-subtle);
}

.data-table td {
  padding: 9px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border-subtle);
  vertical-align: middle;
}

.data-table tbody tr {
  transition: background-color 0.15s ease;
}

.data-table tbody tr:hover {
  background: var(--color-hover-bg);
}

.data-table tbody tr.selected {
  background: var(--color-primary-light);
}

/* Title & Summary Cell */
.title-cell {
  min-width: 260px;
  max-width: 340px;
}

.title-main {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--color-text);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.title-summary-line {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--color-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}

.heat-val {
  font-weight: 700;
  color: var(--color-text);
}

.feedback-adj {
  margin-left: 4px;
  font-size: 11px;
  color: var(--color-primary);
  font-weight: 600;
}

.rag-cell {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.rag-count-pill {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-subtle);
  color: var(--color-muted);
  font-weight: 700;
}

.source-code-text {
  display: inline-block;
  max-width: 110px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}

.time-cell {
  white-space: nowrap;
  font-size: 12px;
  color: var(--color-muted);
}

.feedback-mini {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 60px;
}

.mini-pill {
  display: inline-flex;
  min-height: 20px;
  align-items: center;
  border-radius: 999px;
  padding: 1px 6px;
  font-size: 10.5px;
  font-weight: 700;
  background: var(--surface-subtle);
  color: var(--color-muted);
}

.mini-pill.favorite {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.mini-pill.blocked,
.mini-pill.negative {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.mini-pill.positive {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.mini-pill.none {
  opacity: 0.4;
}

/* Detail Row */
.event-detail-row td {
  background: var(--surface-subtle);
  padding: 0;
}

.event-detail-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-subtle);
}

.detail-section {
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-card);
}

.detail-section h3 {
  margin: 0 0 6px;
  font-size: 12.5px;
  color: var(--color-text);
  font-weight: 700;
}

.detail-section p {
  margin: 0;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 1.6;
}

.full-detail {
  grid-column: 1 / -1;
}

.detail-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.detail-list {
  margin: 0;
  padding-left: 18px;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 1.6;
}

.evidence-links li {
  margin-bottom: 4px;
}

.evidence-links a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
}

.evidence-links a:hover {
  text-decoration: underline;
}

.rag-ref-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.rag-ref-card {
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-subtle);
}

.rag-ref-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
}

.rag-ref-head b {
  color: var(--color-text);
  font-size: 12px;
}

.rag-ref-head span {
  color: var(--color-primary);
  font-size: 11px;
  white-space: nowrap;
}

.rag-ref-card p {
  margin: 6px 0 4px;
  font-size: 11.5px;
  color: var(--color-muted);
}

@media (max-width: 1024px) {
  .event-detail-panel,
  .rag-ref-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .panel-head {
    flex-direction: column;
    align-items: stretch;
  }

  .top-actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }

  .table-search-input {
    width: 100%;
  }

  .table-search-input:focus {
    width: 100%;
  }
}
</style>
