<template>
  <section class="feedback-records-page">
    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>反馈记录</h2>
          <p>集中管理“有用 / 无关 / 收藏 / 屏蔽”，支持分类筛选、勾选批量处理和撤销误操作。</p>
        </div>
        <div class="feedback-actions">
          <select v-model="actionFilter" class="feedback-select" @change="refresh">
            <option value="">全部反馈</option>
            <option value="USEFUL">有用</option>
            <option value="IRRELEVANT">无关</option>
            <option value="FAVORITE">收藏</option>
            <option value="BLOCK">屏蔽</option>
          </select>
          <select v-model="categoryFilter" class="feedback-select" @change="refresh">
            <option value="">全部分类</option>
            <option v-for="name in categoryOptions" :key="name" :value="name">{{ name }}</option>
          </select>
          <select v-model="riskFilter" class="feedback-select" @change="refresh">
            <option value="">全部风险</option>
            <option value="LOW">低风险</option>
            <option value="MEDIUM">中风险</option>
            <option value="HIGH">高风险</option>
          </select>
          <input
            v-model="keyword"
            class="feedback-search"
            placeholder="搜索情报标题 / event_key / 备注"
            @keyup.enter="refresh"
          />
          <button class="ghost-btn" type="button" :disabled="loading" @click="refresh">筛选</button>
          <button class="ghost-btn" type="button" :disabled="loading" @click="resetFilters">重置</button>
        </div>
      </div>

      <div class="feedback-summary-grid">
        <button
          v-for="card in actionCards"
          :key="card.action"
          type="button"
          :class="['summary-card', card.tone, { active: actionFilter === card.action }]"
          @click="setActionFilter(card.action)"
        >
          <span>{{ card.label }}</span>
          <b>{{ summaryCount(card.action) }}</b>
          <small>{{ card.hint }}</small>
        </button>
      </div>

      <div class="filter-toolbar">
        <div class="filter-state">
          <b>当前结果 {{ filteredRecords.length }} 条</b>
          <span v-if="actionFilter">反馈：{{ actionLabel(actionFilter) }}</span>
          <span v-if="categoryFilter">分类：{{ categoryFilter }}</span>
          <span v-if="riskFilter">风险：{{ riskLabel(riskFilter) }}</span>
          <span v-if="keyword.trim()">搜索：{{ keyword.trim() }}</span>
        </div>
        <div v-if="selectedRecords.length" class="bulk-actions">
          <span>已勾选 {{ selectedRecords.length }} 条</span>
          <button class="ghost-btn compact danger" type="button" :disabled="loading" @click="bulkRemoveSelected">
            批量撤销
          </button>
          <button class="ghost-btn compact" type="button" :disabled="loading" @click="clearSelection">
            取消勾选
          </button>
        </div>
      </div>

      <div v-if="!filteredRecords.length && !loading" class="empty-feedback">
        <b>暂无符合条件的反馈记录</b>
        <p>可以调整反馈类型、分类、风险或搜索条件；在今日情报卡片点击反馈按钮后会写入这里。</p>
      </div>

      <div v-else class="feedback-table-wrap">
        <table class="feedback-table">
          <thead>
            <tr>
              <th class="check-col">
                <input
                  v-model="allVisibleSelected"
                  type="checkbox"
                  aria-label="勾选当前筛选结果"
                  :disabled="!filteredRecords.length"
                />
              </th>
              <th>反馈</th>
              <th>分类</th>
              <th>情报</th>
              <th>指标</th>
              <th>操作人</th>
              <th>时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in filteredRecords"
              :key="item.id"
              :class="{ selected: selectedIds.includes(item.id) }"
            >
              <td class="check-col">
                <input
                  v-model="selectedIds"
                  type="checkbox"
                  :value="item.id"
                  :aria-label="`勾选 ${item.event_title || item.event_key}`"
                />
              </td>
              <td>
                <span :class="['action-pill', actionTone(item.action)]">{{ actionLabel(item.action) }}</span>
              </td>
              <td>
                <div class="category-stack">
                  <span class="category-pill">{{ item.event_category || '未分类' }}</span>
                  <span :class="['risk-pill', riskTone(item.event_risk_level)]">{{ riskLabel(item.event_risk_level) }}</span>
                </div>
              </td>
              <td class="record-title-cell">
                <b>{{ item.event_title || item.event_key }}</b>
                <small>{{ item.event_key }}</small>
                <p v-if="item.note">{{ item.note }}</p>
              </td>
              <td>
                <div class="metric-stack">
                  <span>热度 {{ formatNumber(item.event_heat_score) }}</span>
                  <span>来源 {{ item.event_source_count ?? '-' }}</span>
                  <span>可信度 {{ formatNumber(item.event_credibility_score) }} {{ item.event_credibility_level ? riskLabel(item.event_credibility_level) : '' }}</span>
                </div>
              </td>
              <td>{{ item.created_by || 'admin' }}</td>
              <td>{{ formatDateTime(item.updated_at || item.created_at) }}</td>
              <td>
                <button class="ghost-btn compact danger" type="button" :disabled="loading" @click="removeRecord(item)">
                  撤销
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'

import { deleteEventFeedback, listFeedbackRecords } from '@/api/hotspot'
import type { EventFeedbackAction, FeedbackRecord, FeedbackRecordsResult } from '@/types/hotspot'

const emit = defineEmits<{
  (event: 'message', value: string): void
  (event: 'error', value: unknown): void
  (event: 'set-loading', value: boolean): void
}>()

const records = ref<FeedbackRecord[]>([])
const summary = ref<FeedbackRecordsResult['summary']>()
const actionFilter = ref<EventFeedbackAction | ''>('')
const categoryFilter = ref('')
const riskFilter = ref('')
const keyword = ref('')
const loading = ref(false)
const selectedIds = ref<number[]>([])

const actionCards: Array<{ action: EventFeedbackAction; label: string; hint: string; tone: string }> = [
  { action: 'USEFUL', label: '有用', hint: '提升排序权重', tone: 'useful' },
  { action: 'IRRELEVANT', label: '无关', hint: '降低噪声权重', tone: 'irrelevant' },
  { action: 'FAVORITE', label: '收藏', hint: '复盘 / 选题入口', tone: 'favorite' },
  { action: 'BLOCK', label: '屏蔽', hint: '默认不再展示', tone: 'blocked' },
]

const categoryOptions = computed(() => {
  const names = new Set<string>()
  for (const item of records.value) {
    const name = String(item.event_category || '').trim()
    if (name) names.add(name)
  }
  return Array.from(names).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
})

const filteredRecords = computed(() => {
  const category = categoryFilter.value.trim()
  const risk = riskFilter.value.trim().toUpperCase()
  const kw = keyword.value.trim().toLowerCase()
  return records.value.filter((item) => {
    if (category && String(item.event_category || '') !== category) return false
    if (risk && String(item.event_risk_level || '').toUpperCase() !== risk) return false
    if (kw) {
      const haystack = [
        item.event_key,
        item.event_title,
        item.note,
        item.event_category,
        item.event_risk_level,
        item.action,
      ].join(' ').toLowerCase()
      if (!haystack.includes(kw)) return false
    }
    return true
  })
})

const selectedRecords = computed(() => {
  const selected = new Set(selectedIds.value)
  return filteredRecords.value.filter((item) => selected.has(item.id))
})

const allVisibleSelected = computed({
  get() {
    return Boolean(filteredRecords.value.length) && filteredRecords.value.every((item) => selectedIds.value.includes(item.id))
  },
  set(checked: boolean) {
    const visibleIds = filteredRecords.value.map((item) => item.id)
    if (checked) {
      selectedIds.value = Array.from(new Set([...selectedIds.value, ...visibleIds]))
    } else {
      const visibleSet = new Set(visibleIds)
      selectedIds.value = selectedIds.value.filter((id) => !visibleSet.has(id))
    }
  },
})

async function refresh() {
  loading.value = true
  emit('set-loading', true)
  try {
    const data = await listFeedbackRecords({
      action: actionFilter.value,
      keyword: keyword.value.trim() || undefined,
      category: categoryFilter.value.trim() || undefined,
      risk_level: riskFilter.value || undefined,
      limit: 500,
    })
    records.value = data.items || []
    summary.value = data.summary
    pruneSelection()
  } catch (error) {
    emit('error', error)
  } finally {
    loading.value = false
    emit('set-loading', false)
  }
}

function setActionFilter(action: EventFeedbackAction) {
  actionFilter.value = actionFilter.value === action ? '' : action
  selectedIds.value = []
  refresh()
}

function resetFilters() {
  actionFilter.value = ''
  categoryFilter.value = ''
  riskFilter.value = ''
  keyword.value = ''
  selectedIds.value = []
  refresh()
}

function clearSelection() {
  selectedIds.value = []
}

function pruneSelection() {
  const validIds = new Set(records.value.map((item) => item.id))
  selectedIds.value = selectedIds.value.filter((id) => validIds.has(id))
}

async function removeRecord(item: FeedbackRecord) {
  const action = String(item.action || '').toUpperCase() as EventFeedbackAction
  if (!item.event_key || !action) return
  if (!window.confirm(`确定撤销“${actionLabel(action)}”反馈吗？`)) return
  await removeItems([item])
}

async function bulkRemoveSelected() {
  const items = selectedRecords.value
  if (!items.length) return
  if (!window.confirm(`确定撤销已勾选的 ${items.length} 条反馈吗？`)) return
  await removeItems(items)
}

async function removeItems(items: FeedbackRecord[]) {
  loading.value = true
  emit('set-loading', true)
  try {
    let count = 0
    for (const item of items) {
      const action = String(item.action || '').toUpperCase() as EventFeedbackAction
      if (!item.event_key || !action) continue
      await deleteEventFeedback(item.event_key, action)
      count += 1
    }
    emit('message', `已撤销 ${count} 条反馈`)
    selectedIds.value = []
    await refresh()
  } catch (error) {
    emit('error', error)
  } finally {
    loading.value = false
    emit('set-loading', false)
  }
}

function summaryCount(action: EventFeedbackAction): number {
  return Number(summary.value?.counts?.[action] || 0)
}

function actionLabel(action?: string): string {
  const map: Record<string, string> = {
    USEFUL: '有用',
    IRRELEVANT: '无关',
    FAVORITE: '收藏',
    BLOCK: '屏蔽',
  }
  return map[String(action || '').toUpperCase()] || String(action || '-')
}

function actionTone(action?: string): string {
  const value = String(action || '').toUpperCase()
  if (value === 'USEFUL') return 'useful'
  if (value === 'FAVORITE') return 'favorite'
  if (value === 'IRRELEVANT') return 'irrelevant'
  if (value === 'BLOCK') return 'blocked'
  return ''
}

function riskTone(value?: string): string {
  const risk = String(value || '').toUpperCase()
  if (risk === 'HIGH') return 'high'
  if (risk === 'MEDIUM') return 'medium'
  return 'low'
}

function riskLabel(value?: string): string {
  const labels: Record<string, string> = { HIGH: '高', MEDIUM: '中', LOW: '低' }
  return labels[String(value || 'LOW').toUpperCase()] || value || '低'
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm:ss') : value
}

function formatNumber(value?: number): string {
  const num = Number(value || 0)
  if (!num) return '-'
  return Number.isInteger(num) ? String(num) : num.toFixed(1)
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<style scoped>
.feedback-records-page {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.feedback-records-page > .card {
  min-width: 0;
}

.feedback-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.feedback-select,
.feedback-search {
  height: 34px;
  min-height: 34px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-card);
  color: var(--color-text);
  padding: 0 10px;
  font-size: 12.5px;
  outline: none;
}

.feedback-select:focus,
.feedback-search:focus,
.feedback-table input[type='checkbox']:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--glow-accent);
}

.feedback-search {
  width: min(280px, 46vw);
}

.feedback-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 0 18px 16px;
}

.summary-card {
  min-height: 94px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 14px;
  background: var(--surface-subtle);
  text-align: left;
  cursor: pointer;
  transition: var(--transition-smooth);
}

.summary-card:hover,
.summary-card.active {
  border-color: var(--color-primary);
  background: var(--color-hover-bg);
}

.summary-card.active {
  outline: 2px solid var(--border-glow);
}

.summary-card span {
  color: var(--color-muted);
  font-size: 11.5px;
  font-weight: 500;
}

.summary-card b {
  display: block;
  margin-top: 4px;
  color: var(--color-text);
  font-size: 18px;
  font-weight: 650;
  font-family: var(--font-mono);
}

.summary-card small {
  color: var(--color-muted);
  font-size: 11px;
}

.filter-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 0 18px 14px;
  flex-wrap: wrap;
}

.filter-state,
.bulk-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.filter-state b,
.bulk-actions span {
  color: var(--color-text);
  font-size: 13px;
}

.filter-state span {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  color: var(--color-primary);
  background: var(--surface-subtle);
  font-size: 11.5px;
  font-weight: 700;
  border: 1px solid var(--border-subtle);
}

.empty-feedback {
  display: grid;
  place-items: center;
  gap: 8px;
  min-height: 220px;
  padding: 30px;
  text-align: center;
  color: var(--color-muted);
}

.empty-feedback b {
  color: var(--color-text);
}

.feedback-table-wrap {
  padding: 0 18px 18px;
  overflow-x: auto;
  width: 100%;
  max-width: 100%;
  min-width: 0;
}

.feedback-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 1080px;
}

.feedback-table th,
.feedback-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  vertical-align: top;
  color: var(--color-text);
  font-size: 13px;
}

.feedback-table th {
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 700;
  background: var(--surface-glass);
}

.feedback-table tr.selected td {
  background: var(--color-hover-bg);
}

.feedback-table input[type='checkbox'] {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--color-primary);
}

.check-col {
  width: 44px;
}

.record-title-cell {
  max-width: 420px;
}

.record-title-cell b {
  display: block;
  line-height: 1.4;
  color: var(--color-text);
}

.record-title-cell small {
  display: block;
  margin-top: 3px;
  color: var(--color-muted);
  word-break: break-all;
}

.record-title-cell p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  line-height: 1.5;
}

.metric-stack,
.category-stack {
  display: grid;
  gap: 6px;
  color: var(--color-muted);
  font-size: 12px;
}

.action-pill,
.category-pill,
.risk-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 26px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--surface-subtle);
  color: var(--color-muted);
  font-size: 11.5px;
  font-weight: 700;
}

.category-pill {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.action-pill.useful {
  color: #10b981;
  background: rgba(16, 185, 129, 0.14);
}

.action-pill.irrelevant {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.14);
}

.action-pill.favorite {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.14);
}

.action-pill.blocked {
  color: #f43f5e;
  background: rgba(244, 63, 94, 0.14);
}

.risk-pill.low {
  color: #10b981;
  background: rgba(16, 185, 129, 0.14);
}

.risk-pill.medium {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.14);
}

.risk-pill.high {
  color: #f43f5e;
  background: rgba(244, 63, 94, 0.14);
}

.ghost-btn.compact {
  min-height: 32px;
  padding: 6px 10px;
  font-size: 12px;
}

.ghost-btn.danger {
  color: #b91c1c;
}

@media (max-width: 1200px) {
  .feedback-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .panel-head {
    flex-direction: column;
    align-items: stretch;
  }

  .feedback-summary-grid {
    grid-template-columns: 1fr;
  }

  .feedback-actions,
  .feedback-search,
  .feedback-select {
    width: 100%;
  }
}
</style>
