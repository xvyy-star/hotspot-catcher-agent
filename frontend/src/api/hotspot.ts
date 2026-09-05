import axios from 'axios'
import type {
  AIModelProvider,
  AuthLoginResult,
  EventFeedbackAction,
  EventFeedbackItem,
  EventFeedbackSummary,
  FeedbackRecordsResult,
  GenerateBriefingResult,
  BriefingTaskStatus,
  DeploymentReadiness,
  KnowledgeAskResult,
  KnowledgeDocument,
  KnowledgeEmbeddingTestResult,
  KnowledgeIngestRun,
  KnowledgeSearchResult,
  KnowledgeStreamEvent,
  PlatformHotspotFetchResult,
  QQPushConfig,
  SchedulerConfig,
  SystemLogItem,
  SystemMetrics,
  UserProfile,
} from '@/types/hotspot'

const apiBaseURL = import.meta.env.VITE_API_BASE_URL || '/api'
const ADMIN_TOKEN_STORAGE_KEY = 'HOTSPOT_ADMIN_TOKEN'
export const AUTH_EXPIRED_EVENT = 'hotspot:auth-expired'
let authExpiryNotified = false

export function getStoredAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) || ''
}

export function setStoredAdminToken(token: string): void {
  const value = token.trim()
  if (value) {
    localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, value)
    authExpiryNotified = false
  } else {
    localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
  }
}

export function clearStoredAdminToken(): void {
  localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
}

export const DEFAULT_PAGE_KEY = 'hotspot_default_page'
export const REFRESH_INTERVAL_KEY = 'hotspot_refresh_interval'

export function getStoredDefaultPage(): string {
  if (typeof window === 'undefined') return 'dashboard'
  return localStorage.getItem(DEFAULT_PAGE_KEY) || 'dashboard'
}

export function setStoredDefaultPage(page: string): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(DEFAULT_PAGE_KEY, page)
}

export function getStoredRefreshInterval(): number {
  if (typeof window === 'undefined') return 0
  const val = localStorage.getItem(REFRESH_INTERVAL_KEY)
  return val ? parseInt(val, 10) : 0
}

export function setStoredRefreshInterval(seconds: number): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(REFRESH_INTERVAL_KEY, String(seconds))
}

export const api = axios.create({
  baseURL: apiBaseURL,
  timeout: 120000,
})

api.interceptors.request.use((config) => {
  const adminToken = getStoredAdminToken()
  if (adminToken) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${adminToken}`
    config.headers['X-Admin-Token'] = adminToken
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (!error.response) {
      error.message = '后端服务未连接，请确认 FastAPI 已启动，或检查 VITE_API_BASE_URL / Vite proxy 配置。'
    } else if (error.response.status === 401) {
      error.message = error.response.data?.detail || '请重新登录或检查管理员凭据。'
      const requestUrl = String(error.config?.url || '')
      if (getStoredAdminToken() && !requestUrl.includes('/auth/login')) {
        clearStoredAdminToken()
        if (!authExpiryNotified && typeof window !== 'undefined') {
          authExpiryNotified = true
          window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, {
            detail: { message: '登录已过期，请重新登录。' },
          }))
        }
      }
    } else if (error.response.status === 429) {
      error.message = error.response.data?.detail || '请求过于频繁，请稍后再试。'
    }
    return Promise.reject(error)
  },
)

export async function getSystemStatus() {
  const res = await api.get('/system/status')
  return res.data.data
}

export async function loginAdmin(payload: {
  username: string
  password: string
  remember?: boolean
}): Promise<AuthLoginResult> {
  const res = await api.post('/auth/login', payload)
  return res.data.data
}

export async function getCurrentUser(): Promise<UserProfile> {
  const res = await api.get('/auth/me')
  return res.data.data
}

export async function logoutAdmin() {
  const res = await api.post('/auth/logout')
  return res.data
}

export async function changeAdminPassword(payload: {
  old_password: string
  new_password: string
  confirm_password: string
}): Promise<{ ok: boolean; message: string }> {
  const res = await api.post('/auth/change-password', payload)
  return res.data
}

export async function updateUserProfile(payload: {
  display_name: string
}): Promise<{ ok: boolean; message: string; data: UserProfile }> {
  const res = await api.put('/auth/profile', payload)
  return res.data
}

export async function resetLoginFailures(): Promise<{ ok: boolean; message: string }> {
  const res = await api.post('/auth/reset-failures')
  return res.data
}

export async function getSystemLogs(params: {
  limit?: number
  level?: string
  module?: string
  keyword?: string
} = {}): Promise<SystemLogItem[]> {
  const res = await api.get('/system/logs', { params })
  return res.data.data || []
}

export async function deleteSystemLogs(params: {
  level?: string
  module?: string
  keyword?: string
} = {}): Promise<{ deleted_count: number; matched_count: number; scope: 'filtered' | 'all' | string }> {
  const res = await api.delete('/system/logs', { params })
  return res.data.data
}

export async function getSystemMetrics(): Promise<SystemMetrics> {
  const res = await api.get('/system/metrics')
  return res.data.data
}

export async function getDeploymentReadiness(): Promise<DeploymentReadiness> {
  const res = await api.get('/system/readiness')
  return res.data.data
}

export async function getTodayBriefing() {
  const res = await api.get('/hotspots/briefings/today')
  return res.data.data
}

/**
 * [已弃用] P0-6: 同步生成接口已弃用，请使用 generateBriefingAsync。
 * 保留此函数仅为类型兼容，实际调用应使用异步接口。
 */
export async function generateBriefing(): Promise<GenerateBriefingResult> {
  const res = await api.post('/hotspots/briefings/generate')
  return res.data
}

export async function generateBriefingAsync(options: {
  target_date?: string
  trigger?: string
} = {}): Promise<BriefingTaskStatus> {
  const res = await api.post('/hotspots/briefings/generate-async', options)
  return res.data.data
}

export async function regenerateBriefingByDateAsync(date: string): Promise<BriefingTaskStatus> {
  const res = await api.post(`/hotspots/briefings/${date}/regenerate-async`)
  return res.data.data
}

export async function getRunDetail(runId: string): Promise<BriefingTaskStatus> {
  const res = await api.get(`/hotspots/runs/${encodeURIComponent(runId)}`)
  return res.data.data
}

export async function pushTodayBriefing() {
  const res = await api.post('/hotspots/briefings/today/push')
  return res.data
}

export async function getPushConfig() {
  const res = await api.get('/hotspots/push/config')
  return res.data.data
}

export async function savePushConfig(config: QQPushConfig) {
  const res = await api.put('/hotspots/push/config', config)
  return res.data.data
}

export async function testPushConfig(config: QQPushConfig) {
  const res = await api.post('/hotspots/push/config/test', config)
  return res.data
}

export async function getSchedulerConfig() {
  const res = await api.get('/hotspots/scheduler/config')
  return res.data.data
}

export async function getSchedulerStatus() {
  const res = await api.get('/hotspots/scheduler/status')
  return res.data.data
}

export async function saveSchedulerConfig(config: SchedulerConfig) {
  const res = await api.put('/hotspots/scheduler/config', config)
  return res.data
}

export async function runSchedulerNow(force = false) {
  const res = await api.post('/hotspots/scheduler/run', { force })
  return res.data
}

export async function getSourceHealth(limit = 30, live = false, probeLimit = 10, timeout = 12) {
  const res = await api.get('/hotspots/sources/health', {
    params: { limit, live, probe_limit: probeLimit, timeout },
    timeout: live ? 120000 : undefined,
  })
  return res.data.data
}

export async function fetchPlatformHotspots(options: {
  sources?: string[]
  limit?: number
  timeout?: number
} = {}): Promise<PlatformHotspotFetchResult> {
  const res = await api.post('/hotspots/platform-hotspots/fetch', {
    sources: options.sources || ['github', 'huggingface', 'devto'],
    limit: options.limit || 20,
    timeout: options.timeout || 40,
  })
  return res.data.data
}

export async function listEvents(params: Record<string, any> = {}) {
  const res = await api.get('/hotspots/events', { params })
  return res.data.data || []
}

export async function createEventFeedback(eventKey: string, payload: {
  action: EventFeedbackAction
  note?: string
}): Promise<{ feedback: EventFeedbackItem[]; summary: EventFeedbackSummary }> {
  const res = await api.post(`/hotspots/events/${encodeURIComponent(eventKey)}/feedback`, payload)
  return res.data.data
}

export async function deleteEventFeedback(eventKey: string, action: EventFeedbackAction): Promise<{
  deleted_count: number
  feedback: EventFeedbackItem[]
  summary: EventFeedbackSummary
}> {
  const res = await api.delete(`/hotspots/events/${encodeURIComponent(eventKey)}/feedback/${action}`)
  return res.data.data
}

export async function listFeedbackRecords(params: {
  action?: EventFeedbackAction | ''
  keyword?: string
  category?: string
  risk_level?: string
  limit?: number
} = {}): Promise<FeedbackRecordsResult> {
  const res = await api.get('/hotspots/feedback', { params })
  return res.data.data || { items: [] }
}

export async function listRuns(limit = 20) {
  const res = await api.get('/hotspots/runs', { params: { limit } })
  return res.data.data || []
}

export async function listBriefings(limit = 50) {
  const res = await api.get('/hotspots/briefings', { params: { limit } })
  return res.data.data || []
}

export async function getBriefingByDate(date: string) {
  const res = await api.get(`/hotspots/briefings/${date}`)
  return res.data.data
}

/**
 * [已弃用] P0-6: 同步重生成接口已弃用，请使用 regenerateBriefingByDateAsync。
 */
export async function regenerateBriefingByDate(date: string): Promise<GenerateBriefingResult> {
  const res = await api.post(`/hotspots/briefings/${date}/regenerate`)
  return res.data
}

export async function listModelProviders() {
  const res = await api.get('/models/providers')
  return res.data.data || []
}

export async function getModelCallStats(limit = 50) {
  const res = await api.get('/models/stats', { params: { limit } })
  return res.data.data
}

export async function saveModelProvider(provider: AIModelProvider) {
  const payload = { ...provider }
  if (!payload.api_key) {
    delete payload.api_key
  }
  if (provider.id) {
    const res = await api.put(`/models/providers/${provider.id}`, payload)
    return res.data.data
  }
  const res = await api.post('/models/providers', payload)
  return res.data.data
}

export async function deleteModelProvider(id: number) {
  const res = await api.delete(`/models/providers/${id}`)
  return res.data
}

export async function fetchProviderModels(id: number) {
  const res = await api.post(`/models/providers/${id}/models`)
  return res.data.data || []
}

export async function testModelProvider(id: number) {
  const res = await api.post(`/models/providers/${id}/test`)
  return res.data
}

export async function probeModels(provider: Pick<AIModelProvider, 'base_url' | 'api_key' | 'timeout_seconds'>) {
  const res = await api.post('/models/probe/models', provider)
  return res.data.data || []
}

export async function probeProviderTest(provider: Pick<AIModelProvider, 'base_url' | 'api_key' | 'model' | 'timeout_seconds'>) {
  const res = await api.post('/models/probe/test', provider)
  return res.data
}

export async function getKnowledgeHealth() {
  const res = await api.get('/knowledge/health')
  return res.data.data
}

export async function testKnowledgeEmbedding(text = 'AI Agent 热点捕手 RAG 向量模型连通性测试'): Promise<KnowledgeEmbeddingTestResult> {
  const res = await api.post('/knowledge/embedding/test', { text })
  return res.data.data
}

export async function reindexKnowledgeVectorsAsync(options: {
  document_id?: number
  batch_size?: number
  recreate_collection?: boolean
} = {}): Promise<KnowledgeIngestRun> {
  const res = await api.post('/knowledge/reindex/async', options)
  return res.data.data
}

export async function listKnowledgeDocuments(limit = 50): Promise<KnowledgeDocument[]> {
  const res = await api.get('/knowledge/documents', { params: { limit } })
  return res.data.data || []
}

export async function listKnowledgeIngestRuns(params: {
  limit?: number
  status?: string
  document_id?: number
} = {}) {
  const res = await api.get('/knowledge/ingest-runs', { params })
  return res.data.data || []
}

export async function getKnowledgeIngestRun(runId: number): Promise<KnowledgeIngestRun> {
  const res = await api.get(`/knowledge/ingest-runs/${runId}`)
  return res.data.data
}

export async function createKnowledgeDocument(payload: {
  title: string
  content: string
  source?: string
  tags?: string[]
  chunk_size?: number
  overlap?: number
}) {
  const res = await api.post('/knowledge/documents', payload)
  return res.data.data
}

export async function createKnowledgeDocumentAsync(payload: {
  title: string
  content: string
  source?: string
  tags?: string[]
  chunk_size?: number
  overlap?: number
}): Promise<KnowledgeIngestRun> {
  const res = await api.post('/knowledge/documents/async', payload)
  return res.data.data
}

export async function uploadKnowledgeDocument(
  file: File,
  options: {
    title?: string
    source?: string
    tags?: string
    chunk_size?: number
    overlap?: number
  } = {},
) {
  const form = new FormData()
  form.append('file', file)
  Object.entries(options).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      form.append(key, String(value))
    }
  })
  const res = await api.post('/knowledge/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
  return res.data.data
}

export async function uploadKnowledgeDocumentAsync(
  file: File,
  options: {
    title?: string
    source?: string
    tags?: string
    chunk_size?: number
    overlap?: number
  } = {},
): Promise<KnowledgeIngestRun> {
  const form = new FormData()
  form.append('file', file)
  Object.entries(options).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      form.append(key, String(value))
    }
  })
  const res = await api.post('/knowledge/documents/upload/async', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
  return res.data.data
}

export async function deleteKnowledgeDocument(id: number) {
  const res = await api.delete(`/knowledge/documents/${id}`)
  return res.data
}

export async function searchKnowledge(query: string, top_k = 5, document_ids: number[] = []): Promise<KnowledgeSearchResult[]> {
  const res = await api.post('/knowledge/search', { query, top_k, document_ids })
  return res.data.data || []
}

export async function askKnowledge(question: string, top_k = 5, document_ids: number[] = []): Promise<KnowledgeAskResult> {
  const res = await api.post('/knowledge/ask', { question, top_k, document_ids })
  return res.data.data
}

export async function askKnowledgeStream(
  question: string,
  top_k = 5,
  document_ids: number[] = [],
  onEvent: (event: KnowledgeStreamEvent) => void,
): Promise<void> {
  const adminToken = getStoredAdminToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (adminToken) {
    headers.Authorization = `Bearer ${adminToken}`
    headers['X-Admin-Token'] = adminToken
  }

  const endpoint = `${apiBaseURL.replace(/\/$/, '')}/knowledge/ask/stream`
  const response = await fetch(endpoint, {
    method: 'POST',
    headers,
    body: JSON.stringify({ question, top_k, document_ids }),
  })
  if (!response.ok) {
    throw new Error(`流式问答请求失败：HTTP ${response.status}`)
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持 ReadableStream')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const consumeLine = (line: string) => {
    const trimmed = line.trim()
    if (!trimmed) return
    const event = JSON.parse(trimmed) as KnowledgeStreamEvent
    onEvent(event)
    if (event.type === 'error') {
      throw new Error(event.message || event.error || '流式问答失败')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) consumeLine(line)
  }
  buffer += decoder.decode()
  if (buffer.trim()) consumeLine(buffer)
}

export async function ingestLatestBriefingToKnowledge() {
  const res = await api.post('/knowledge/ingest/latest-briefing')
  return res.data.data
}

export async function ingestLatestBriefingToKnowledgeAsync(options: {
  briefing_date?: string
  chunk_size?: number
  overlap?: number
} = {}): Promise<KnowledgeIngestRun> {
  const res = await api.post('/knowledge/ingest/latest-briefing/async', options)
  return res.data.data
}
