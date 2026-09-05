<template>
  <section class="data-board-page">
    <div class="card data-board-hero">
      <div>
        <span class="eyebrow">运行概览</span>
        <h2>系统健康状态</h2>
        <p>汇总采集、模型、知识库、推送和系统日志的当前状态。</p>
      </div>
      <div class="board-score">
        <strong>{{ formatNumber(metrics?.summary.system_score) }}</strong>
        <span>系统健康分</span>
        <em>{{ scoreHint }}</em>
      </div>
    </div>

    <div class="board-kpi-grid">
      <div v-for="card in kpiCards" :key="card.label" :class="['card', 'board-kpi-card', card.tone]">
        <span>{{ card.label }}</span>
        <b>{{ card.value }}</b>
        <p>{{ card.hint }}</p>
      </div>
    </div>

    <div class="card panel readiness-panel">
      <div class="panel-head readiness-head">
        <div>
          <span class="eyebrow">上线准备度</span>
          <h2>上线交付检查</h2>
          <p>{{ readiness?.summary || '正在汇总安全、真实数据、采集源、模型与运维检查项。' }}</p>
        </div>
        <div :class="['readiness-score', readinessTone]">
          <strong>{{ formatNumber(readiness?.readiness_score) }}</strong>
          <span>{{ readinessLevelText }}</span>
        </div>
      </div>

      <div class="readiness-overview">
        <div v-for="card in readinessCards" :key="card.label" :class="['readiness-mini-card', card.tone]">
          <span>{{ card.label }}</span>
          <b>{{ card.value }}</b>
          <p>{{ card.hint }}</p>
        </div>
      </div>

      <div class="readiness-layout">
        <div class="readiness-category-list">
          <h3>模块自检状态</h3>
          <div
            v-for="category in readiness?.categories || []"
            :key="category.code"
            :class="['readiness-category-card', statusTone(category.status)]"
          >
            <div>
              <b>{{ category.name }}</b>
              <span>{{ category.summary }}</span>
            </div>
            <em :class="['badge', statusTone(category.status)]">{{ statusLabel(category.status) }}</em>
          </div>
          <p v-if="!(readiness?.categories || []).length" class="empty-hint">暂无上线检查结果</p>
        </div>

        <div class="readiness-action-list">
          <h3>优先处理项</h3>
          <div v-for="item in readinessActions" :key="item.code" :class="['readiness-action-item', statusTone(item.status)]">
            <div class="readiness-action-title">
              <b>{{ item.title }}</b>
              <span>{{ categoryLabel(item.category) }} · {{ severityLabel(item.severity) }}</span>
            </div>
            <p>{{ humanizeStatusText(item.description) }}</p>
            <small v-if="item.evidence">证据：{{ humanizeStatusText(item.evidence) }}</small>
            <em v-if="item.action">建议：{{ humanizeStatusText(item.action) }}</em>
          </div>
          <p v-if="!readinessActions.length" class="empty-hint">当前没有阻塞项或警告项</p>
        </div>
      </div>
    </div>

    <div class="card panel">
      <div class="panel-head small">
        <h2>人工反馈闭环</h2>
        <span class="badge ai">反馈闭环</span>
      </div>
      <div class="feedback-board-grid">
        <div class="feedback-board-card positive">
          <span>正向反馈</span>
          <b>{{ metrics?.feedback?.positive_count ?? 0 }}</b>
          <p>有用 + 收藏，用于提升排序权重</p>
        </div>
        <div class="feedback-board-card negative">
          <span>负向反馈</span>
          <b>{{ metrics?.feedback?.negative_count ?? 0 }}</b>
          <p>无关 + 屏蔽，用于降低或隐藏噪声</p>
        </div>
        <div class="feedback-board-card favorite">
          <span>收藏情报</span>
          <b>{{ metrics?.feedback?.favorite_count ?? 0 }}</b>
          <p>可作为复盘、选题和知识库沉淀入口</p>
        </div>
        <div class="feedback-board-card blocked">
          <span>已屏蔽</span>
          <b>{{ metrics?.feedback?.blocked_count ?? 0 }}</b>
          <p>默认不进入首页和热点池展示</p>
        </div>
      </div>
    </div>

    <div class="board-layout">
      <div class="card panel">
        <div class="panel-head small">
          <h2>近 7 日趋势</h2>
          <span class="badge ai">{{ metrics?.today || '-' }}</span>
        </div>
        <div class="trend-chart">
          <div v-for="point in eventTrend" :key="point.date" class="trend-column">
            <div class="trend-bars">
              <span class="briefing-bar" :style="{ height: barHeight(point.briefings, maxTrendValue) }"></span>
              <span class="event-bar" :style="{ height: barHeight(point.events, maxTrendValue) }"></span>
            </div>
            <small>{{ dayLabel(point.date) }}</small>
          </div>
        </div>
        <div class="chart-legend">
          <span><i class="event-dot"></i> 热点事件</span>
          <span><i class="briefing-dot"></i> 简报归档</span>
        </div>
      </div>

      <div class="card panel">
        <div class="panel-head small">
          <h2>链路健康</h2>
          <span :class="['badge', metrics?.summary.errors_24h ? 'high' : 'low']">
            {{ metrics?.summary.errors_24h ? '需关注' : '正常' }}
          </span>
        </div>
        <div class="health-stack">
          <div v-for="item in healthBars" :key="item.label" class="health-line">
            <div>
              <b>{{ item.label }}</b>
              <span>{{ item.value }}</span>
            </div>
            <div class="health-bar">
              <i :class="item.tone" :style="{ width: item.percent + '%' }"></i>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card panel">
      <div class="panel-head small">
        <div>
          <h2>近 7 日运行质量</h2>
          <p>任务、模型与推送的实际执行结果</p>
        </div>
        <span class="badge ai">每日汇总</span>
      </div>
      <div class="operations-table-wrap">
        <table class="operations-table">
          <thead>
            <tr>
              <th scope="col">日期</th>
              <th scope="col">任务执行</th>
              <th scope="col">模型调用</th>
              <th scope="col">Token / 成本</th>
              <th scope="col">推送执行</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="point in operationTrend" :key="point.date">
              <td>{{ dayLabel(point.date) }}</td>
              <td>
                <b>{{ rateOrDash(point.run_success_rate, point.runs_total) }}</b>
                <small>成功 {{ point.runs_success }}/{{ point.runs_total }} · 跳过 {{ point.runs_skipped }}</small>
              </td>
              <td>
                <b>{{ rateOrDash(point.llm_success_rate, point.llm_calls) }}</b>
                <small>成功 {{ point.llm_success }}/{{ point.llm_calls }} · 失败 {{ point.llm_failed }}</small>
              </td>
              <td>
                <b>{{ formatCount(point.llm_tokens) }}</b>
                <small>{{ formatUsd(point.llm_cost) }} · {{ point.llm_calls }} 次调用</small>
              </td>
              <td>
                <b>{{ rateOrDash(point.push_success_rate, point.push_total) }}</b>
                <small>成功 {{ point.push_success }}/{{ point.push_total }} · 失败 {{ point.push_failed }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="board-layout">
      <div class="card panel">
        <div class="panel-head small">
          <h2>热点分类分布</h2>
        </div>
        <div class="distribution-list">
          <div v-for="item in metrics?.distributions.category || []" :key="item.name" class="distribution-row">
            <span>{{ item.name }}</span>
            <b>{{ item.count }}</b>
            <div><i :style="{ width: item.percent + '%' }"></i></div>
          </div>
          <p v-if="!(metrics?.distributions.category || []).length" class="empty-hint">暂无分类数据</p>
        </div>
      </div>

      <div class="card panel">
        <div class="panel-head small">
          <h2>来源分布</h2>
        </div>
        <div class="distribution-list">
          <div v-for="item in metrics?.distributions.source || []" :key="item.name" class="distribution-row">
            <span>{{ item.name }}</span>
            <b>{{ item.count }}</b>
            <div><i class="source" :style="{ width: item.percent + '%' }"></i></div>
          </div>
          <p v-if="!(metrics?.distributions.source || []).length" class="empty-hint">暂无来源数据</p>
        </div>
      </div>
    </div>

    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>最近任务与异常</h2>
          <p>看板只放最近记录；需要完整排查请进入“系统日志”和“运行记录”。</p>
        </div>
        <button class="ghost-btn" type="button" :disabled="busy" @click="refresh">
          <RefreshCw :class="{ spinning: busy }" /> 刷新
        </button>
      </div>
      <div class="board-bottom-grid">
        <div class="mini-table-wrap">
          <h3>最近 Agent Run</h3>
          <div v-for="run in metrics?.recent_runs || []" :key="run.id" class="mini-row">
            <div>
              <b>{{ run.run_id }}</b>
              <span>{{ formatDateTime(run.started_at) }}</span>
            </div>
            <em :class="['badge', statusClass(run.status)]">{{ statusLabel(run.status) }}</em>
          </div>
          <p v-if="!(metrics?.recent_runs || []).length" class="empty-hint">暂无任务</p>
        </div>
        <div class="mini-table-wrap">
          <h3>最近系统日志</h3>
          <div v-for="log in metrics?.logs.recent || []" :key="log.id" class="mini-row log">
            <div>
              <b>{{ moduleLabel(log.module) }} · {{ humanizeStatusText(log.message) }}</b>
              <span>{{ formatDateTime(log.created_at) }} {{ log.trace_id ? `· ${log.trace_id}` : '' }}</span>
            </div>
            <em :class="['badge', logClass(log.level)]">{{ logLevelLabel(log.level) }}</em>
          </div>
          <p v-if="!(metrics?.logs.recent || []).length" class="empty-hint">暂无日志</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { RefreshCw } from 'lucide-vue-next'
import { getDeploymentReadiness, getSystemMetrics } from '@/api/hotspot'
import type { DeploymentReadiness, DeploymentReadinessItem, SystemMetrics } from '@/types/hotspot'

const emit = defineEmits<{
  (e: 'message', text: string): void
  (e: 'error', err: any): void
  (e: 'set-loading', loading: boolean): void
}>()

const metrics = ref<SystemMetrics | null>(null)
const readiness = ref<DeploymentReadiness | null>(null)
const busy = ref(false)

const scoreHint = computed(() => {
  const score = metrics.value?.summary.system_score || 0
  if (score >= 85) return '状态优秀'
  if (score >= 70) return '可稳定演示'
  if (score >= 55) return '需关注链路'
  return '建议先排障'
})

const kpiCards = computed(() => {
  const s = metrics.value?.summary
  return [
    { label: '今日热点', value: s?.today_events ?? '-', hint: `总事件 ${s?.total_events ?? 0}`, tone: 'blue' },
    { label: '平均可信度', value: `${formatNumber(s?.avg_credibility)}%`, hint: `样例/模拟入库 ${s?.fallback_sample_count ?? 0}`, tone: 'green' },
    { label: '采集成功率', value: formatPercent(s?.source_success_rate || 0), hint: `健康源 ${s?.healthy_sources ?? 0}/${s?.enabled_sources ?? 0}`, tone: 'teal' },
    { label: '任务成功率', value: rateOrDash(s?.run_success_rate_7d || 0, s?.runs_7d || 0), hint: `7 日失败 ${s?.run_failed_7d ?? 0} · 平均 ${formatDuration(s?.avg_run_duration_seconds)}`, tone: 'blue' },
    { label: '模型成功率', value: formatPercent(s?.model_success_rate || 0), hint: `24h 调用 ${s?.llm_calls_24h ?? 0}`, tone: 'purple' },
    { label: '24h 模型成本', value: formatUsd(s?.llm_cost_24h), hint: `Token ${formatCount(s?.llm_tokens_24h)} · 7 日 ${formatUsd(s?.llm_cost_7d)}`, tone: 'amber' },
    { label: 'RAG 命中率', value: formatPercent(s?.rag_hit_rate || 0), hint: '热点带知识库引用比例', tone: 'amber' },
    { label: '推送成功率', value: rateOrDash(s?.push_success_rate || 0, (s?.push_success_count || 0) + (s?.push_failed_count || 0)), hint: `成功 ${s?.push_success_count ?? 0} · 失败 ${s?.push_failed_count ?? 0} · 跳过 ${s?.push_skipped_count ?? 0}`, tone: 'teal' },
    { label: '反馈正向率', value: rateOrDash(s?.feedback_positive_rate || 0, s?.feedback_total_count || 0), hint: `正向 ${s?.feedback_positive_count ?? 0} · 负向 ${s?.feedback_negative_count ?? 0}`, tone: 'green' },
    { label: '24h 异常', value: s?.errors_24h ?? '-', hint: `警告 ${s?.warnings_24h ?? 0}`, tone: s?.errors_24h ? 'red' : 'green' },
  ]
})

const eventTrend = computed(() => {
  const events = metrics.value?.trends.events_7d || []
  const briefings = metrics.value?.trends.briefings_7d || []
  const map = new Map(briefings.map((item) => [item.date, item.count]))
  return events.map((item) => ({ date: item.date, events: item.count, briefings: map.get(item.date) || 0 }))
})

const maxTrendValue = computed(() => Math.max(1, ...eventTrend.value.flatMap((item) => [item.events, item.briefings])))

const operationTrend = computed(() => metrics.value?.trends.operations_7d || [])

const healthBars = computed(() => {
  const s = metrics.value?.summary
  return [
    { label: '采集源', value: formatPercent(s?.source_success_rate || 0), percent: clamp(s?.source_success_rate || 0), tone: 'green' },
    { label: '模型调用', value: formatPercent(s?.model_success_rate || 0), percent: clamp(s?.model_success_rate || 0), tone: 'blue' },
    { label: 'RAG 引用', value: formatPercent(s?.rag_hit_rate || 0), percent: clamp(s?.rag_hit_rate || 0), tone: 'purple' },
    { label: '推送成功', value: rateOrDash(s?.push_success_rate || 0, (s?.push_success_count || 0) + (s?.push_failed_count || 0)), percent: clamp(s?.push_success_rate || 0), tone: 'teal' },
  ]
})

const readinessTone = computed(() => statusTone(readiness.value?.production_ready ? 'PASS' : readiness.value?.blockers ? 'FAIL' : 'WARN'))

const readinessLevelText = computed(() => {
  const level = readiness.value?.readiness_level
  if (level === 'READY') return '可部署验收'
  if (level === 'BLOCKED') return '存在阻塞'
  if (level === 'NEEDS_ATTENTION') return '需要关注'
  return '待检查'
})

const readinessCards = computed(() => {
  const r = readiness.value
  return [
    { label: '阻塞项', value: r?.blockers ?? '-', hint: '必须先处理的红色风险', tone: (r?.blockers || 0) > 0 ? 'red' : 'green' },
    { label: '警告项', value: r?.warnings ?? '-', hint: '上线前建议确认', tone: (r?.warnings || 0) > 0 ? 'amber' : 'green' },
    { label: '通过项', value: r?.passed ?? '-', hint: `共 ${r?.total_items ?? 0} 个检查项`, tone: 'blue' },
    { label: '最近任务', value: statusLabel(r?.latest_run?.status), hint: r?.latest_run?.run_id || '暂无运行记录', tone: statusTone(r?.latest_run?.status || undefined) },
  ]
})

const readinessActions = computed<DeploymentReadinessItem[]>(() => readiness.value?.top_actions?.slice(0, 6) || [])

async function refresh() {
  busy.value = true
  emit('set-loading', true)
  try {
    const [metricsResult, readinessResult] = await Promise.allSettled([
      getSystemMetrics(),
      getDeploymentReadiness(),
    ])
    if (metricsResult.status === 'fulfilled') {
      metrics.value = metricsResult.value
    } else {
      emit('error', metricsResult.reason)
    }
    if (readinessResult.status === 'fulfilled') {
      readiness.value = readinessResult.value
    } else {
      emit('error', readinessResult.reason)
    }
  } catch (error) {
    emit('error', error)
  } finally {
    busy.value = false
    emit('set-loading', false)
  }
}

function clamp(value: number): number {
  return Math.max(0, Math.min(100, Number(value || 0)))
}

function barHeight(value: number, maxValue: number): string {
  return `${Math.max(8, Math.round((Number(value || 0) / Math.max(1, maxValue)) * 120))}px`
}

function dayLabel(value: string): string {
  const d = dayjs(value)
  return d.isValid() ? d.format('MM-DD') : value
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const d = dayjs(value)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : value
}

function formatNumber(value?: number): string {
  const num = Number(value || 0)
  return Number.isInteger(num) ? String(num) : num.toFixed(1)
}

function formatPercent(value: number): string {
  const num = Number(value || 0)
  const normalized = num <= 1 ? num * 100 : num
  return `${Math.round(normalized)}%`
}

function rateOrDash(value: number, total: number): string {
  return Number(total || 0) > 0 ? formatPercent(value) : '-'
}

function formatCount(value?: number): string {
  return Math.max(0, Number(value || 0)).toLocaleString('zh-CN')
}

function formatUsd(value?: number): string {
  const cost = Math.max(0, Number(value || 0))
  return cost < 0.01 ? `$${cost.toFixed(6)}` : `$${cost.toFixed(2)}`
}

function formatDuration(value?: number): string {
  const seconds = Math.max(0, Number(value || 0))
  if (!seconds) return '-'
  if (seconds < 60) return `${Math.round(seconds)}秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
  return `${(seconds / 3600).toFixed(1)}小时`
}

function statusClass(status?: string): string {
  if (status === 'SUCCESS') return 'low'
  if (status === 'FAILED') return 'high'
  return 'medium'
}

function statusTone(status?: string): string {
  if (status === 'PASS' || status === 'READY' || status === 'SUCCESS' || status === 'SKIPPED') return 'low'
  if (status === 'FAIL' || status === 'BLOCKED' || status === 'FAILED') return 'high'
  return 'medium'
}

function statusLabel(status?: string | null): string {
  const labels: Record<string, string> = {
    PASS: '通过',
    READY: '就绪',
    SUCCESS: '成功',
    SKIPPED: '已跳过',
    WARN: '警告',
    WARNING: '警告',
    NEEDS_ATTENTION: '需关注',
    FAIL: '未通过',
    FAILED: '失败',
    BLOCKED: '阻塞',
    RUNNING: '运行中',
    QUEUED: '排队中',
  }
  return labels[String(status || '').toUpperCase()] || status || '待检查'
}

function humanizeStatusText(value?: string): string {
  if (!value) return ''
  return value.replace(
    /\b(PASS|READY|SUCCESS|SKIPPED|WARN|WARNING|NEEDS_ATTENTION|FAIL|FAILED|BLOCKED|RUNNING|QUEUED)\b/g,
    (status) => statusLabel(status),
  )
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

function severityLabel(severity?: string): string {
  const labels: Record<string, string> = { HIGH: '高优先级', MEDIUM: '中优先级', LOW: '低优先级' }
  return labels[String(severity || '').toUpperCase()] || severity || '-'
}

function categoryLabel(code?: string): string {
  const category = readiness.value?.categories?.find((item) => item.code === code)
  return category?.name || code || '-'
}

function logClass(level?: string): string {
  if (level === 'ERROR' || level === 'CRITICAL') return 'high'
  if (level === 'WARNING') return 'medium'
  return 'low'
}

onMounted(refresh)

defineExpose({ refresh })
</script>

<style scoped>
.data-board-page {
  display: grid;
  gap: 12px;
}

.data-board-page > * {
  min-width: 0;
}

.data-board-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
}

.eyebrow {
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.data-board-hero h2 {
  margin: 4px 0 0;
  color: var(--color-text);
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.data-board-hero p {
  max-width: 780px;
  margin: 4px 0 0;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 1.5;
}

.board-score {
  min-width: 140px;
  min-height: 48px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-subtle);
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  text-align: left;
  gap: 2px 8px;
}

.board-score strong {
  grid-row: 1 / 3;
  color: var(--color-text);
  font-size: 20px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.board-score span,
.board-score em {
  color: var(--color-muted);
  font-size: 11px;
  font-style: normal;
}

.board-kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.board-kpi-card {
  min-height: 74px;
  padding: 10px 12px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.board-kpi-card span {
  color: var(--color-muted);
  font-size: 11px;
}

.board-kpi-card b {
  display: block;
  margin-top: 4px;
  color: var(--color-text);
  font-size: 17px;
  font-weight: 650;
  font-family: var(--font-mono);
}

.board-kpi-card p {
  margin: 3px 0 0;
  color: var(--color-muted);
  font-size: 11px;
}

.board-kpi-card.blue,
.board-kpi-card.green,
.board-kpi-card.teal,
.board-kpi-card.purple,
.board-kpi-card.amber,
.board-kpi-card.red {
  border-color: var(--border-subtle);
  background: var(--surface-card);
}

.readiness-panel {
  overflow: hidden;
  border-color: var(--border-subtle);
  background: var(--surface-card);
}

.readiness-head {
  align-items: center;
  border-bottom: 1px solid var(--border-subtle);
  padding: 12px 18px;
}

.readiness-head h2 {
  margin: 3px 0 0;
  color: var(--color-text);
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.readiness-head p {
  max-width: 880px;
  margin: 4px 0 0;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 1.5;
}

.readiness-score {
  flex: 0 0 auto;
  width: 90px;
  min-height: 60px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 2px;
  background: var(--surface-subtle);
  padding: 6px;
}

.readiness-score strong {
  color: var(--color-text);
  font-size: 20px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.readiness-score span {
  color: var(--color-muted);
  font-size: 11px;
  font-weight: 600;
}

.readiness-score.low { border-left: 3px solid #10b981; background: var(--surface-subtle); }
.readiness-score.medium { border-left: 3px solid #f59e0b; background: var(--surface-subtle); }
.readiness-score.high { border-left: 3px solid #f43f5e; background: var(--surface-subtle); }

.readiness-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 12px 18px;
}

.readiness-mini-card {
  min-height: 68px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--surface-subtle);
}

.readiness-mini-card span {
  color: var(--color-muted);
  font-size: 11px;
  font-weight: 500;
}

.readiness-mini-card b {
  display: block;
  margin-top: 3px;
  color: var(--color-text);
  font-size: 17px;
  font-weight: 650;
  font-family: var(--font-mono);
}

.readiness-mini-card p {
  margin: 3px 0 0;
  color: var(--color-muted);
  font-size: 11px;
  line-height: 1.4;
  word-break: break-word;
}

.readiness-mini-card.blue,
.readiness-mini-card.green,
.readiness-mini-card.low,
.readiness-mini-card.amber,
.readiness-mini-card.medium,
.readiness-mini-card.red,
.readiness-mini-card.high {
  border-color: var(--border-subtle);
  background: var(--surface-subtle);
}

.readiness-layout {
  display: grid;
  grid-template-columns: minmax(260px, .8fr) minmax(0, 1.2fr);
  gap: 16px;
  padding: 0 20px 20px;
}

.readiness-category-list,
.readiness-action-list {
  display: grid;
  gap: 10px;
}

.readiness-category-card {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  background: var(--surface-subtle);
}

.readiness-category-card.low { border-left: 3px solid #10b981; background: var(--surface-subtle); }
.readiness-category-card.medium { border-left: 3px solid #f59e0b; background: var(--surface-subtle); }
.readiness-category-card.high { border-left: 3px solid #f43f5e; background: var(--surface-subtle); }

.readiness-category-card b {
  display: block;
  color: var(--color-text);
  font-size: 13px;
}

.readiness-category-card span {
  display: block;
  margin-top: 4px;
  color: var(--color-muted);
  font-size: 12px;
}

.readiness-category-card em {
  flex: 0 0 auto;
  font-style: normal;
}

.readiness-category-list h3,
.readiness-action-list h3 {
  margin: 0 0 4px;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}

.readiness-action-item {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 14px;
  background: var(--surface-subtle);
}

.readiness-action-item.low { border-left: 3px solid #10b981; background: var(--surface-subtle); }
.readiness-action-item.medium { border-left: 3px solid #f59e0b; background: var(--surface-subtle); }
.readiness-action-item.high { border-left: 3px solid #f43f5e; background: var(--surface-subtle); }

.readiness-action-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.readiness-action-title b {
  color: var(--color-text);
  font-size: 13px;
}

.readiness-action-title span {
  flex: 0 0 auto;
  color: var(--color-muted);
  font-size: 11px;
}

.readiness-action-item p,
.readiness-action-item small,
.readiness-action-item em {
  display: block;
  margin-top: 7px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
  font-style: normal;
}

.readiness-action-item em {
  color: #f59e0b;
  font-weight: 700;
}

.feedback-board-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 10px 18px 16px;
}

.feedback-board-card {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--surface-subtle);
}

.feedback-board-card span {
  color: var(--color-muted);
  font-size: 11px;
  font-weight: 500;
}

.feedback-board-card b {
  display: block;
  margin-top: 3px;
  color: var(--color-text);
  font-size: 17px;
  font-weight: 650;
  font-family: var(--font-mono);
}

.feedback-board-card p {
  margin: 3px 0 0;
  color: var(--color-muted);
  font-size: 11px;
  line-height: 1.4;
}

.feedback-board-card.positive,
.feedback-board-card.negative,
.feedback-board-card.favorite,
.feedback-board-card.blocked {
  border-color: var(--border-subtle);
  background: var(--surface-subtle);
}

.board-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, .85fr);
  gap: 16px;
}

.trend-chart {
  height: 180px;
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  align-items: end;
  gap: 12px;
  padding: 10px 4px 0;
}

.trend-column {
  display: grid;
  gap: 8px;
  justify-items: center;
}

.trend-bars {
  height: 132px;
  display: flex;
  align-items: end;
  gap: 5px;
}

.trend-bars span {
  width: 16px;
  border-radius: 999px 999px 4px 4px;
}

.event-bar { background: var(--color-primary); }
.briefing-bar { background: #5e7181; }

.trend-column small,
.chart-legend {
  color: var(--color-muted);
  font-size: 12px;
}

.chart-legend {
  display: flex;
  gap: 16px;
  margin-top: 10px;
}

.chart-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chart-legend i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.operations-table-wrap {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.operations-table {
  width: 100%;
  min-width: 820px;
  border-collapse: collapse;
}

.operations-table th,
.operations-table td {
  border-bottom: 1px solid var(--color-border);
  padding: 11px 12px;
  text-align: left;
  vertical-align: top;
}

.operations-table th {
  color: var(--color-muted);
  font-size: 11px;
  font-weight: 700;
}

.operations-table td {
  color: var(--color-text);
  font-size: 12px;
}

.operations-table td:first-child {
  white-space: nowrap;
}

.operations-table td b,
.operations-table td small {
  display: block;
}

.operations-table td b {
  font-size: 13px;
}

.operations-table td small {
  margin-top: 4px;
  color: var(--color-muted);
  white-space: nowrap;
}

.operations-table tbody tr:last-child td {
  border-bottom: 0;
}

.event-dot { background: #1a73e8; }
.briefing-dot { background: #34a853; }

.health-stack {
  display: grid;
  gap: 18px;
}

.health-line > div:first-child {
  display: flex;
  justify-content: space-between;
  margin-bottom: 7px;
  color: var(--color-text);
  font-size: 13px;
}

.health-line span {
  color: var(--color-muted);
}

.health-bar {
  height: 9px;
  border-radius: 999px;
  background: var(--surface-subtle);
  overflow: hidden;
}

.health-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.health-bar i.green { background: #10b981; }
.health-bar i.blue { background: var(--color-primary); }
.health-bar i.purple { background: #a855f7; }
.health-bar i.teal { background: #14b8a6; }

.distribution-list {
  display: grid;
  gap: 12px;
}

.distribution-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 44px;
  gap: 8px;
  align-items: center;
}

.distribution-row span {
  color: var(--color-text);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.distribution-row b {
  color: var(--color-muted);
  text-align: right;
  font-size: 12px;
}

.distribution-row div {
  grid-column: 1 / -1;
  height: 7px;
  border-radius: 999px;
  background: var(--surface-subtle);
  overflow: hidden;
}

.distribution-row i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
}

.distribution-row i.source {
  background: #14b8a6;
}

.board-bottom-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.mini-table-wrap h3 {
  margin: 0 0 10px;
  color: var(--color-text);
  font-size: 14px;
}

.mini-row {
  min-height: 58px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 8px;
  background: var(--surface-subtle);
}

.mini-row b {
  display: -webkit-box;
  color: var(--color-text);
  font-size: 12px;
  line-height: 1.5;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mini-row span {
  display: block;
  margin-top: 4px;
  color: var(--color-muted);
  font-size: 11px;
}

.mini-row em {
  flex: 0 0 auto;
  font-style: normal;
}

.mini-row.log b {
  word-break: break-word;
}

@media (max-width: 1200px) {
  .board-kpi-grid,
  .feedback-board-grid,
  .readiness-overview {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .data-board-hero {
    align-items: flex-start;
    flex-direction: column;
  }
  .board-layout,
  .board-bottom-grid,
  .readiness-layout {
    grid-template-columns: 1fr;
  }
  .readiness-head {
    align-items: flex-start;
  }
}

@media (max-width: 640px) {
  .board-kpi-grid,
  .feedback-board-grid,
  .readiness-overview {
    grid-template-columns: 1fr;
  }
  .readiness-action-title,
  .readiness-category-card {
    flex-direction: column;
  }
}
</style>
