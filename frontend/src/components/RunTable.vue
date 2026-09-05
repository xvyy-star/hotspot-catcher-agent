<template>
  <div class="card panel">
    <div class="panel-head">
      <div class="panel-head-left">
        <div class="panel-title-row">
          <h2>Agent 运行记录</h2>
          <span class="count-badge">共 {{ filteredRuns.length }} 次运行</span>
        </div>
        <p>每次早报生成都会记录 run，便于排查失败、统计耗时和审计任务链路。</p>
      </div>
      <div class="top-actions">
        <div class="filter-pills">
          <button
            type="button"
            :class="['filter-pill', { active: statusFilter === '' }]"
            @click="statusFilter = ''"
          >
            全部 ({{ runs.length }})
          </button>
          <button
            type="button"
            :class="['filter-pill', { active: statusFilter === 'SUCCESS' }]"
            @click="statusFilter = 'SUCCESS'"
          >
            成功 ({{ countByStatus('SUCCESS') }})
          </button>
          <button
            type="button"
            :class="['filter-pill', 'danger-pill', { active: statusFilter === 'FAILED' }]"
            @click="statusFilter = 'FAILED'"
          >
            失败 ({{ countByStatus('FAILED') }})
          </button>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>状态</th>
            <th>原始条数</th>
            <th>提炼事件</th>
            <th>知识库入库</th>
            <th>开始时间</th>
            <th>结束时间</th>
            <th>执行错误信息</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in filteredRuns" :key="run.id">
            <td>
              <span class="run-id-pill" :title="run.run_id">{{ run.run_id }}</span>
            </td>
            <td>
              <span :class="['badge', statusBadgeClass(run.status)]">{{ statusLabel(run.status) }}</span>
            </td>
            <td class="num-cell">{{ run.total_raw }}</td>
            <td class="num-cell">{{ run.total_events }}</td>
            <td>
              <template v-if="runKnowledgeIngest(run)">
                <span :class="['badge', statusBadgeClass(runKnowledgeIngestStatus(run))]">
                  {{ runKnowledgeIngestLabel(run) }}
                </span>
                <div class="muted-text-compact">{{ runKnowledgeIngestHint(run) }}</div>
              </template>
              <span v-else class="muted-text">未触发</span>
            </td>
            <td class="time-cell">{{ formatDateTime(run.started_at) }}</td>
            <td class="time-cell">{{ formatDateTime(run.finished_at) }}</td>
            <td class="error-col">
              <template v-if="run.error_message">
                <div class="error-snippet" :title="run.error_message">
                  {{ run.error_message.slice(0, 50) }}{{ run.error_message.length > 50 ? '...' : '' }}
                </div>
                <button
                  class="ghost-btn compact-copy-btn"
                  type="button"
                  title="复制完整错误日志"
                  @click="copyError(run.error_message)"
                >
                  {{ copiedId === run.id ? '已复制' : '复制日志' }}
                </button>
              </template>
              <span v-else class="muted-dash">-</span>
            </td>
          </tr>
          <tr v-if="!filteredRuns.length">
            <td colspan="8" class="empty-cell">
              {{ statusFilter ? '当前筛选状态下暂无运行记录' : '暂无运行记录' }}
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
import type { AgentRun, KnowledgeIngestRun, KnowledgeAutoIngestResult } from '@/types/hotspot'

const props = defineProps<{
  runs: AgentRun[]
  ingestRuns: KnowledgeIngestRun[]
}>()

const statusFilter = ref('')
const copiedId = ref<number | null>(null)

const filteredRuns = computed(() => {
  if (!statusFilter.value) return props.runs
  return props.runs.filter(r => {
    const s = String(r.status || '').toUpperCase()
    if (statusFilter.value === 'SUCCESS') {
      return s === 'SUCCESS' || s === 'COMPLETED' || s === 'READY'
    }
    if (statusFilter.value === 'FAILED') {
      return s === 'FAILED' || s === 'ERROR'
    }
    return s === statusFilter.value
  })
})

function countByStatus(type: 'SUCCESS' | 'FAILED'): number {
  return props.runs.filter(r => {
    const s = String(r.status || '').toUpperCase()
    if (type === 'SUCCESS') return s === 'SUCCESS' || s === 'COMPLETED' || s === 'READY'
    if (type === 'FAILED') return s === 'FAILED' || s === 'ERROR'
    return false
  }).length
}

function copyError(msg: string) {
  navigator.clipboard.writeText(msg).catch(() => {})
}

function runKnowledgeIngest(run: AgentRun): KnowledgeAutoIngestResult | null {
  return (run.meta?.knowledge_ingest as KnowledgeAutoIngestResult | undefined) || null
}

function runKnowledgeIngestLive(run: AgentRun): KnowledgeIngestRun | null {
  const auto = runKnowledgeIngest(run)
  if (!auto?.run_id) return null
  return props.ingestRuns.find((row) => row.id === auto.run_id) || null
}

function runKnowledgeIngestStatus(run: AgentRun): string {
  const auto = runKnowledgeIngest(run)
  const live = runKnowledgeIngestLive(run)
  return live?.status || auto?.status || (auto?.queued ? 'QUEUED' : 'SKIPPED')
}

function runKnowledgeIngestLabel(run: AgentRun): string {
  const auto = runKnowledgeIngest(run)
  return `#${auto?.run_id || '-'} · ${statusLabel(runKnowledgeIngestStatus(run))}`
}

function runKnowledgeIngestHint(run: AgentRun): string {
  const auto = runKnowledgeIngest(run)
  const live = runKnowledgeIngestLive(run)
  if (!auto) return '未触发'
  if (live?.status === 'SUCCESS') return `${live.document_title || '历史早报'}，${live.chunk_count || 0} 个分块`
  if (live?.status === 'FAILED') return live.error_message || '入库失败'
  if (!auto.queued) return auto.error_message || '未入队'
  return auto.duplicate_policy || '异步入库中'
}

function statusBadgeClass(status?: string): string {
  if (status === 'SUCCESS' || status === 'ACTIVE' || status === 'READY' || status === 'COMPLETED') return 'low'
  if (status === 'FAILED' || status === 'ERROR') return 'high'
  return 'medium'
}

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    SUCCESS: '成功',
    ACTIVE: '已启用',
    READY: '就绪',
    COMPLETED: '已完成',
    QUEUED: '排队中',
    PENDING: '等待中',
    PARSING: '解析中',
    CHUNKING: '分块中',
    EMBEDDING: '向量化中',
    VECTOR_UPSERT: '写入向量库',
    RUNNING: '运行中',
    SKIPPED: '已跳过',
    FAILED: '失败',
    ERROR: '异常',
  }
  return labels[String(status || '').toUpperCase()] || status || '待检查'
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = dayjs(value)
  return date.isValid() ? date.format('MM-DD HH:mm:ss') : value
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

.filter-pills {
  display: flex;
  gap: 6px;
  background: var(--surface-subtle);
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
}

.filter-pill {
  border: none;
  background: transparent;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--color-muted);
  cursor: pointer;
  transition: var(--transition-fast);
}

.filter-pill:hover {
  color: var(--color-text);
}

.filter-pill.active {
  background: var(--surface-card);
  color: var(--color-text);
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.filter-pill.danger-pill.active {
  color: #ef4444;
}

.table-wrap {
  max-height: calc(100vh - 240px);
  overflow: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
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
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border-subtle);
  vertical-align: middle;
}

.run-id-pill {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface-subtle);
  color: var(--color-text);
  border: 1px solid var(--border-subtle);
}

.num-cell {
  font-weight: 600;
  color: var(--color-text);
}

.time-cell {
  font-size: 12px;
  color: var(--color-muted);
  white-space: nowrap;
}

.muted-text-compact {
  font-size: 11px;
  color: var(--color-muted);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.error-col {
  max-width: 260px;
}

.error-snippet {
  font-size: 11.5px;
  color: #ef4444;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.compact-copy-btn {
  margin-top: 3px;
  padding: 1px 6px;
  font-size: 10.5px;
  border-radius: 4px;
}

.muted-dash {
  color: var(--color-muted);
  opacity: 0.5;
}
</style>
