<template>
  <section class="system-log-page">
    <div class="card panel log-filter-card">
      <div class="log-filters">
        <label class="form-item">
          <span>级别</span>
          <select v-model="filters.level">
            <option value="">全部</option>
            <option value="INFO">信息</option>
            <option value="WARNING">警告</option>
            <option value="ERROR">错误</option>
            <option value="CRITICAL">严重</option>
          </select>
        </label>
        <label class="form-item">
          <span>模块</span>
          <select v-model="filters.module">
            <option value="">全部</option>
            <option v-for="module in moduleOptions" :key="module" :value="module">{{ moduleLabel(module) }}</option>
          </select>
        </label>
        <label class="form-item wide">
          <span>关键词 / trace_id / run_id</span>
          <input v-model="filters.keyword" placeholder="例如 startup / ERROR / run_xxx" @keydown.enter="refresh" />
        </label>
        <label class="form-item">
          <span>条数</span>
          <input v-model.number="filters.limit" type="number" min="20" max="500" />
        </label>
        <div class="filter-buttons">
          <button class="ghost-btn" type="button" @click="resetFilters">重置</button>
          <button class="primary-btn" type="button" :disabled="busy" @click="refresh">查询</button>
          <button class="danger-btn" type="button" :disabled="busy" @click="handleDeleteLogs">
            删除{{ hasActiveFilters ? '筛选结果' : '全部' }}
          </button>
        </div>
      </div>
      <p class="delete-rule-note">
        删除规则：按当前级别、模块、关键词筛选条件删除；如果没有任何筛选条件，将删除全部系统日志。
      </p>
    </div>

    <div class="log-summary-grid">
      <div v-for="item in summaryCards" :key="item.label" :class="['card', 'log-summary-card', item.tone]">
        <span>{{ item.label }}</span>
        <b>{{ item.value }}</b>
        <p>{{ item.hint }}</p>
      </div>
    </div>

    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>日志明细</h2>
          <p>点击 trace_id / run_id 可复制，便于和接口响应、任务记录对齐。</p>
        </div>
        <span class="badge ai">{{ filteredLogs.length }} / {{ logs.length }}</span>
      </div>
      <div class="table-wrap">
        <table class="data-table log-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>级别</th>
              <th>模块</th>
              <th>消息</th>
              <th>Trace / Run</th>
              <th>扩展</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in filteredLogs" :key="log.id">
              <td class="nowrap">{{ formatDateTime(log.created_at) }}</td>
              <td><span :class="['badge', logClass(log.level)]">{{ logLevelLabel(log.level) }}</span></td>
              <td><span class="module-pill">{{ moduleLabel(log.module) }}</span></td>
              <td class="log-message">{{ humanizeStatusText(log.message) }}</td>
              <td class="trace-cell">
                <button v-if="log.trace_id" type="button" @click="copyText(log.trace_id)">trace {{ shortText(log.trace_id, 18) }}</button>
                <button v-if="log.run_id" type="button" @click="copyText(log.run_id)">run {{ shortText(log.run_id, 18) }}</button>
                <span v-if="!log.trace_id && !log.run_id">-</span>
              </td>
              <td class="extra-cell">{{ compactExtra(log.extra_json) }}</td>
            </tr>
            <tr v-if="!filteredLogs.length">
              <td colspan="6" class="empty-cell">暂无系统日志</td>
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
import { deleteSystemLogs, getSystemLogs } from '@/api/hotspot'
import type { SystemLogItem } from '@/types/hotspot'

const emit = defineEmits<{
  (e: 'message', text: string): void
  (e: 'error', err: any): void
  (e: 'set-loading', loading: boolean): void
}>()

const logs = ref<SystemLogItem[]>([])
const busy = ref(false)
const filters = ref({
  level: '',
  module: '',
  keyword: '',
  limit: 120,
})

const moduleOptions = computed(() => Array.from(new Set(logs.value.map((item) => item.module).filter(Boolean))).sort())
const filteredLogs = computed(() => logs.value)
const hasActiveFilters = computed(() => Boolean(filters.value.level || filters.value.module || filters.value.keyword.trim()))

const summaryCards = computed(() => {
  const total = logs.value.length
  const errors = logs.value.filter((item) => item.level === 'ERROR' || item.level === 'CRITICAL').length
  const warnings = logs.value.filter((item) => item.level === 'WARNING').length
  const modules = moduleOptions.value.length
  return [
    { label: '日志总数', value: total, hint: `当前查询窗口 ${filters.value.limit} 条`, tone: 'blue' },
    { label: '错误', value: errors, hint: errors ? '需要优先排查' : '当前窗口无错误', tone: errors ? 'red' : 'green' },
    { label: '警告', value: warnings, hint: '配置或链路退化信号', tone: warnings ? 'amber' : 'green' },
    { label: '模块数', value: modules, hint: moduleOptions.value.map(moduleLabel).join(' / ') || '-', tone: 'teal' },
  ]
})

async function refresh() {
  busy.value = true
  emit('set-loading', true)
  try {
    logs.value = await getSystemLogs({
      limit: filters.value.limit,
      level: filters.value.level || undefined,
      module: filters.value.module || undefined,
      keyword: filters.value.keyword || undefined,
    })
  } catch (error) {
    emit('error', error)
  } finally {
    busy.value = false
    emit('set-loading', false)
  }
}

function resetFilters() {
  filters.value = { level: '', module: '', keyword: '', limit: 120 }
  refresh()
}

async function handleDeleteLogs() {
  const scopeText = hasActiveFilters.value
    ? `当前筛选条件下的日志（级别：${filters.value.level ? logLevelLabel(filters.value.level) : '全部'}；模块：${filters.value.module ? moduleLabel(filters.value.module) : '全部'}；关键词：${filters.value.keyword || '无'}）`
    : '全部系统日志'
  const expected = logs.value.length
  const confirmed = window.confirm(
    `确认删除${scopeText}？\n\n当前页面匹配 ${expected} 条。该操作不可恢复。`,
  )
  if (!confirmed) return

  busy.value = true
  emit('set-loading', true)
  try {
    const result = await deleteSystemLogs({
      level: filters.value.level || undefined,
      module: filters.value.module || undefined,
      keyword: filters.value.keyword.trim() || undefined,
    })
    emit('message', `已删除 ${result.deleted_count} 条系统日志`)
    await refresh()
  } catch (error) {
    emit('error', error)
  } finally {
    busy.value = false
    emit('set-loading', false)
  }
}

async function copyText(text?: string) {
  if (!text) return
  await navigator.clipboard.writeText(text)
  emit('message', '已复制到剪贴板')
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const d = dayjs(value)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : value
}

function shortText(text?: string, max = 40): string {
  if (!text) return '-'
  return text.length > max ? `${text.slice(0, max)}...` : text
}

function compactExtra(value: any): string {
  if (!value) return '-'
  try {
    return shortText(JSON.stringify(value), 80)
  } catch {
    return shortText(String(value), 80)
  }
}

function logClass(level?: string): string {
  if (level === 'ERROR' || level === 'CRITICAL') return 'high'
  if (level === 'WARNING') return 'medium'
  return 'low'
}

function logLevelLabel(level?: string): string {
  const labels: Record<string, string> = {
    INFO: '信息',
    WARNING: '警告',
    ERROR: '错误',
    CRITICAL: '严重',
  }
  return labels[String(level || '').toUpperCase()] || level || '-'
}

function moduleLabel(module?: string): string {
  const labels: Record<string, string> = {
    agent: '任务执行',
    api: '接口服务',
    auth: '登录认证',
    'briefing-task': '简报任务',
    'data-quality': '数据质量',
    feedback: '反馈管理',
    manual: '手动操作',
    models: '模型服务',
    push: '消息推送',
    scheduler: '自动任务',
    startup: '服务启动',
    system: '系统',
  }
  return labels[String(module || '').toLowerCase()] || module || '-'
}

function humanizeStatusText(value?: string): string {
  if (!value) return ''
  const labels: Record<string, string> = {
    SUCCESS: '成功',
    FAILED: '失败',
    RUNNING: '运行中',
    QUEUED: '排队中',
    SKIPPED: '已跳过',
    READY: '就绪',
  }
  return value.replace(/\b(SUCCESS|FAILED|RUNNING|QUEUED|SKIPPED|READY)\b/g, (status) => labels[status] || status)
}

onMounted(refresh)

defineExpose({ refresh })
</script>

<style scoped>
.system-log-page {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.system-log-page > .card,
.log-summary-grid,
.log-summary-card,
.table-wrap {
  min-width: 0;
  max-width: 100%;
}

.log-filter-card {
  padding: 16px 20px;
}

.log-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}

.log-filters .form-item {
  flex: 0 0 130px;
}

.log-filters .form-item.wide {
  flex: 1 1 240px;
}

.log-filters .form-item:nth-child(4) {
  flex: 0 0 90px;
}

.filter-buttons {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-left: auto;
}

.filter-buttons button {
  height: 36px;
  min-height: 36px;
  padding: 0 14px;
  font-size: 12.5px;
  font-weight: 600;
  border-radius: 8px;
}

.danger-btn {
  height: 36px;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(244, 63, 94, 0.3);
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #f87171;
  background: rgba(244, 63, 94, 0.12);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition-fast);
  white-space: nowrap;
}

.danger-btn:hover:not(:disabled) {
  background: rgba(244, 63, 94, 0.22);
  border-color: rgba(244, 63, 94, 0.5);
  color: #f43f5e;
}

.danger-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.delete-rule-note {
  margin: 10px 0 0;
  color: var(--color-muted);
  font-size: 11.5px;
  line-height: 1.5;
}

.log-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.log-summary-card {
  padding: 10px 12px;
  border-radius: 8px;
}

.log-summary-card span {
  color: var(--color-muted);
  font-size: 11px;
}

.log-summary-card b {
  display: block;
  margin-top: 4px;
  color: var(--color-text);
  font-size: 18px;
  font-weight: 650;
  font-family: var(--font-mono);
}

.log-summary-card p {
  margin: 3px 0 0;
  color: var(--color-muted);
  font-size: 11px;
  line-height: 1.4;
}

.log-summary-card.blue,
.log-summary-card.green,
.log-summary-card.red,
.log-summary-card.amber,
.log-summary-card.teal {
  border-color: var(--border-subtle);
  background: var(--surface-card);
}

.log-table {
  width: 100%;
  border-collapse: collapse;
}

.log-table th,
.log-table td {
  padding: 10px 14px;
  font-size: 12px;
  line-height: 1.5;
  letter-spacing: normal;
}

.log-table td {
  vertical-align: top;
}

.nowrap {
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--color-muted);
}

.module-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 4px;
  color: var(--color-primary);
  background: rgba(0, 242, 254, 0.12);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: normal;
  white-space: nowrap;
}

.log-message {
  min-width: 240px;
  color: var(--color-text);
  line-height: 1.55;
  word-break: break-word;
  font-size: 12.5px;
  letter-spacing: normal;
}

.trace-cell {
  min-width: 140px;
  white-space: nowrap;
}

.trace-cell button {
  display: inline-block;
  margin-bottom: 4px;
  padding: 2px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--color-primary);
  background: var(--surface-subtle);
  font-size: 11px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: var(--transition-fast);
}

.trace-cell button:hover {
  border-color: var(--color-primary);
  background: var(--color-active-bg);
}

.extra-cell {
  max-width: 280px;
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.4;
  word-break: break-all;
  letter-spacing: normal;
}

@media (max-width: 1100px) {
  .log-filters,
  .log-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .log-filters,
  .log-summary-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .filter-buttons {
    flex-direction: column;
    width: 100%;
  }
  .filter-buttons button {
    width: 100%;
  }
}
</style>
