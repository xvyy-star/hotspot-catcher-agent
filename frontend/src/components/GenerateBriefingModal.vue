<template>
  <div v-if="visible" class="chrome-modal-overlay">
    <div class="chrome-modal-card" role="dialog" aria-modal="true" aria-labelledby="briefing-progress-title">
      <div class="chrome-spinner-container">
        <div class="chrome-spinner"></div>
      </div>
      <h3 id="briefing-progress-title" class="chrome-modal-title">正在生成热点早报</h3>
      <p class="chrome-modal-desc">任务已在后端异步执行，页面会自动轮询状态；你可以看到 run_id、进度和知识库入库状态。</p>
      <div v-if="task" class="modal-task-card">
        <div class="modal-task-head">
          <b>后端任务</b>
          <span :class="['badge', statusBadgeClass(task.status)]">{{ statusLabel(task.status) }}</span>
        </div>
        <div class="modal-progress"><i :style="{ width: `${Math.max(8, Math.min(100, Number(task.progress || 0)))}%` }"></i></div>
        <p>任务 ID：{{ task.run_id }} · 事件 {{ task.total_events ?? task.meta?.api_result?.total_events ?? '-' }} · 原始数据 {{ task.total_raw ?? '-' }}</p>
      </div>
      <div class="chrome-modal-steps">
        <div
          v-for="(step, index) in steps"
          :key="step"
          class="modal-step"
          :class="{ 'step-active': currentStep === index, 'step-done': currentStep > index, 'step-pending': currentStep < index }"
          v-show="currentStep >= index"
        >
          <CheckCircle2 v-if="currentStep > index" />
          <Clock3 v-else />
          <span>{{ step }}</span>
        </div>
      </div>
      <div v-if="autoIngest" class="modal-ingest-card">
        <div class="modal-ingest-head">
          <b>知识库自动入库</b>
          <span :class="['badge', statusBadgeClass(ingestStatus || (autoIngest.queued ? 'QUEUED' : 'SKIPPED'))]">
            {{ statusLabel(ingestStatus || (autoIngest.queued ? 'QUEUED' : 'SKIPPED')) }}
          </span>
        </div>
        <p>{{ ingestMessage }}</p>
        <div class="modal-ingest-meta">
          <span>任务 ID：{{ autoIngest.run_id || '-' }}</span>
          <span>策略：{{ duplicatePolicyLabel(autoIngest.duplicate_policy) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CheckCircle2, Clock3 } from 'lucide-vue-next'
import type { BriefingTaskStatus, KnowledgeAutoIngestResult } from '@/types/hotspot'

defineProps<{
  visible: boolean
  steps: string[]
  currentStep: number
  autoIngest: KnowledgeAutoIngestResult | null
  ingestStatus: string
  ingestMessage: string
  task?: BriefingTaskStatus | null
}>()

function statusBadgeClass(status?: string): string {
  if (status === 'SUCCESS' || status === 'COMPLETED' || status === 'READY') return 'low'
  if (status === 'FAILED' || status === 'ERROR') return 'high'
  return 'medium'
}

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    SUCCESS: '成功',
    COMPLETED: '已完成',
    READY: '就绪',
    QUEUED: '排队中',
    PENDING: '等待中',
    RUNNING: '运行中',
    SKIPPED: '已跳过',
    FAILED: '失败',
    ERROR: '异常',
  }
  return labels[String(status || '').toUpperCase()] || status || '待检查'
}

function duplicatePolicyLabel(policy?: string): string {
  if (policy === 'skip_same_content_replace_changed') return '同内容跳过，内容变化则替换'
  return policy || '-'
}
</script>

<style scoped>
.modal-task-card {
  width: 100%;
  margin: 14px 0 4px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 12px;
  background: var(--surface-subtle);
}
.modal-task-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.modal-task-head b { color: var(--color-text); }
.modal-progress {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--border-subtle);
}
.modal-progress i {
  transition: width .25s ease;
}
.modal-task-card p {
  margin: 8px 0 0;
  color: var(--color-muted, #64748b);
  font-size: 12px;
  word-break: break-all;
}
</style>
