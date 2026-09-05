export interface PlatformHotspotItem {
  source: string
  source_name: string
  title: string
  url?: string
  source_item_id?: string
  rank?: number
  raw_hot_score?: string
  content?: string
  tags?: string[]
  captured_at?: string
  raw_payload?: Record<string, any>
}

export interface PlatformHotspotFetchSourceResult {
  code: string
  name: string
  status: 'SUCCESS' | 'FAILED' | string
  count: number
  items: PlatformHotspotItem[]
  error?: string
}

export interface PlatformHotspotFetchResult {
  sources: Record<string, PlatformHotspotFetchSourceResult>
  total: number
  limit: number
  timeout: number
}

export interface UserProfile {
  username: string
  display_name: string
  role: string
  avatar_text: string
  permissions: string[]
  auth_mode: string
  auth_modes?: string[]
  api_auth_enabled: boolean
  login_security?: {
    client_ip?: string
    failed_count: number
    locked_until?: string | null
    last_failed_at?: string | null
    last_success_at?: string | null
    last_success_ip?: string | null
    last_auth_mode?: string | null
    last_logout_at?: string | null
    failure_limit: number
    lock_seconds: number
    password_enabled: boolean
    password_hash_configured: boolean
  }
}

export interface AuthLoginResult {
  token: string
  profile: UserProfile
  login_at: string
  expires_in: number
}

export type EventFeedbackAction = 'USEFUL' | 'IRRELEVANT' | 'FAVORITE' | 'BLOCK'

export interface EventFeedbackSummary {
  counts?: Partial<Record<EventFeedbackAction, number>>
  positive_count?: number
  negative_count?: number
  is_favorite?: boolean
  is_blocked?: boolean
  score_adjustment?: number
}

export interface EventFeedbackItem {
  id: number
  event_key: string
  action: EventFeedbackAction | string
  note?: string
  created_by?: string
  created_at?: string
  updated_at?: string
}

export interface FeedbackRecord extends EventFeedbackItem {
  event_title?: string
  event_category?: string
  event_heat_score?: number
  event_risk_level?: string
  event_source_count?: number
  event_credibility_score?: number
  event_credibility_level?: string
}

export interface FeedbackRecordsResult {
  items: FeedbackRecord[]
  summary?: {
    counts?: Partial<Record<EventFeedbackAction, number>>
    positive_count?: number
    negative_count?: number
    blocked_count?: number
    favorite_count?: number
  }
}

export interface HotspotEvent {
  id: number
  event_key: string
  title: string
  items?: PlatformHotspotItem[]
  summary?: string
  category?: string
  heat_score: number
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH'
  risk_reason?: string
  source_codes?: string[]
  source_count: number
  main_opinions?: string[]
  opposing_opinions?: string[]
  content_suggestions?: string[]
  rag_references?: Array<{
    document_id: number
    document_title: string
    chunk_id: number
    chunk_index: number
    score: number
    source?: string
    preview?: string
  }>
  historical_insights?: string[]
  knowledge_relevance_score?: number
  knowledge_relevance_level?: string
  business_relevance?: string
  business_relevance_reason?: string
  analysis_mode?: 'LLM' | 'LLM_CACHE' | 'RULE' | 'RULE_FALLBACK'
  analysis_model?: string
  analysis_latency_ms?: number
  analysis_error?: string
  credibility_score?: number
  credibility_level?: 'LOW' | 'MEDIUM' | 'HIGH' | string
  credibility_reason?: string
  is_fallback_sample?: boolean
  has_real_evidence?: boolean
  feedback?: EventFeedbackSummary
  display_heat_score?: number
  score_adjustment?: number
  created_at?: string
  updated_at?: string
}

export interface DailyBriefing {
  id: number
  briefing_date: string
  title: string
  summary?: string
  markdown?: string
  raw_json?: {
    events?: HotspotEvent[]
    source_health?: Record<string, any>
  }
  status: string
  created_at?: string
  updated_at?: string
}

export interface KnowledgeAutoIngestResult {
  enabled: boolean
  queued: boolean
  mode?: string
  briefing_date?: string
  run_id?: number
  status?: string
  duplicate_policy?: string
  error_message?: string
}

export interface GenerateBriefingResult {
  run_id?: string
  status: string
  message?: string
  total_events?: number
  briefing?: {
    briefing_date?: string
    title?: string
    summary?: string
    markdown?: string
    events?: HotspotEvent[]
    status?: string
    source_health?: Record<string, any>
  }
  knowledge_ingest?: KnowledgeAutoIngestResult
}

export interface BriefingTaskStatus {
  id?: number
  run_id: string
  status: string
  progress?: number
  started_at?: string
  finished_at?: string
  total_raw?: number
  total_events?: number
  error_message?: string
  target_date?: string
  trigger?: string
  mode?: string
  message?: string
  queued_at?: string
  reused?: boolean
  meta?: Record<string, any>
  knowledge_ingest?: KnowledgeAutoIngestResult
}

export interface AgentRun {
  id: number
  run_id: string
  status: string
  started_at: string
  finished_at?: string
  total_raw: number
  total_events: number
  error_message?: string
  meta?: Record<string, any>
}

export interface AIModelProvider {
  id?: number
  code: string
  name: string
  base_url: string
  api_key?: string
  api_key_masked?: string
  api_key_configured?: boolean
  uses_env_api_key?: boolean
  model: string
  priority: number
  enabled: boolean
  requires_api_key: boolean
  timeout_seconds: number
  max_tokens: number
  temperature: number
  input_cost_per_million: number
  output_cost_per_million: number
  note?: string
  last_test_status?: string
  last_test_message?: string
  last_test_at?: string
  created_at?: string
  updated_at?: string
}

export interface ModelTestResult {
  ok: boolean
  status_code?: number
  latency_ms?: number
  message?: string
}

export interface LLMProviderStat {
  provider_code?: string
  provider_name?: string
  model?: string
  total_calls: number
  success_count: number
  failed_count: number
  cache_hit_count: number
  avg_latency_ms: number
  total_tokens: number
  total_estimated_cost: number
  success_rate: number
}

export interface LLMCallLog {
  id: number
  run_id?: string
  event_key?: string
  title?: string
  provider_code?: string
  provider_name?: string
  model?: string
  status: 'SUCCESS' | 'FAILED' | 'CACHE_HIT' | string
  cache_hit: boolean
  latency_ms?: number
  error_message?: string
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  estimated_cost?: number
  created_at?: string
}

export interface ModelCallStats {
  total_calls: number
  success_count: number
  failed_count: number
  cache_hit_count: number
  avg_latency_ms: number
  success_rate: number
  total_tokens: number
  total_estimated_cost: number
  provider_stats: LLMProviderStat[]
  recent_calls: LLMCallLog[]
}

export interface QQPushConfig {
  channel: 'qq_bot' | string
  enabled: boolean
  onebot_api_base: string
  target_type: 'private' | 'group'
  user_id?: string
  group_id?: string
  access_token?: string
  access_token_masked?: string
  retry_times: number
  timeout_seconds: number
  max_chars: number
  allow_partial_success: boolean
  local_config_path?: string
}

export interface PushTestResult {
  ok: boolean
  status_code?: number
  latency_ms?: number
  message?: string
  data?: any
}

export interface SchedulerConfig {
  enabled: boolean
  hour: number
  minute: number
  timezone: string
  job_id?: string
  allow_rerun_same_day: boolean
  lock_ttl_minutes: number
  retry_times: number
  retry_delay_seconds: number
  misfire_grace_seconds: number
  coalesce: boolean
  max_instances: number
  local_config_path?: string
}

export interface SchedulerStatus {
  config: SchedulerConfig
  knowledge_auto_ingest?: {
    auto_ingest_daily_briefing: boolean
    auto_ingest_triggers: string[]
    chunk_size: number
    overlap: number
    duplicate_policy: string
  }
  scheduler_running: boolean
  job_exists: boolean
  job_id: string
  next_run_time?: string
  today: string
  today_has_briefing: boolean
  today_briefing_status?: string
  today_briefing_updated_at?: string
  running_count: number
  lock_key: string
  local_config_path?: string
}

export interface SchedulerRunResult {
  run_id?: string
  status: string
  message?: string
  lock_backend?: string
  lock_message?: string
  knowledge_ingest?: KnowledgeAutoIngestResult
}

export interface SourceHealthRecent {
  run_id: string
  run_at?: string
  status: 'SUCCESS' | 'FALLBACK' | 'FAILED' | 'DISABLED' | string
  count: number
  real_count: number
  fallback_count: number
  dropped_fallback_count?: number
  dropped_no_evidence_count?: number
  error?: string
}

export interface SourceLiveProbeItem {
  title: string
  url?: string
  rank?: number
  raw_hot_score?: string
  source_item_id?: string
  category?: string
  is_fallback_sample?: boolean
  real_source?: boolean
  has_real_evidence?: boolean
}

export interface SourceLiveProbe {
  code: string
  checked_at?: string
  latency_ms: number
  status: 'SUCCESS' | 'FALLBACK' | 'FAILED' | 'DISABLED' | 'UNKNOWN' | string
  count: number
  real_count: number
  fallback_count: number
  dropped_fallback_count?: number
  dropped_no_evidence_count?: number
  preview_count: number
  items_preview: SourceLiveProbeItem[]
  error?: string
  message?: string
}

export interface SourceHealthItem {
  code: string
  name: string
  enabled: boolean
  weight: number
  strategy: string
  note?: string
  source_url?: string
  domains?: string[]
  max_items: number
  attempts: number
  success_count: number
  fallback_count: number
  failed_count: number
  disabled_count: number
  success_rate: number
  availability_rate: number
  total_items: number
  real_items: number
  fallback_items: number
  dropped_fallback_count?: number
  dropped_no_evidence_count?: number
  latest_status: 'SUCCESS' | 'FALLBACK' | 'FAILED' | 'DISABLED' | 'NO_DATA' | string
  latest_run_id?: string
  latest_run_at?: string
  latest_error?: string
  last_captured_at?: string
  raw_item_total: number
  health_level: 'HEALTHY' | 'DEGRADED' | 'UNSTABLE' | 'DOWN' | 'DISABLED' | 'UNKNOWN' | string
  status_counts: Record<string, number>
  recent: SourceHealthRecent[]
  live_probe?: SourceLiveProbe
  live_checked_at?: string
  live_status?: string
  live_real_items?: number
  live_fallback_items?: number
  live_dropped_no_evidence_items?: number
  live_latency_ms?: number
}

export interface SourceHealthReport {
  window_run_limit: number
  recent_run_count: number
  latest_run_at?: string
  total_sources: number
  enabled_sources: number
  healthy_sources: number
  degraded_sources: number
  down_sources: number
  unknown_sources: number
  avg_success_rate: number
  live_probe?: {
    enabled: boolean
    checked_at?: string
    probe_limit?: number
    timeout?: number
    total?: number
    success?: number
    fallback?: number
    failed?: number
    disabled?: number
    dropped_fallback_count?: number
    dropped_no_evidence_count?: number
  }
  items: SourceHealthItem[]
}

export interface SystemLogItem {
  id: number
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL' | string
  module: string
  message: string
  trace_id?: string
  run_id?: string
  extra_json?: Record<string, any> | any[]
  created_at?: string
}

export interface SystemMetricPoint {
  date: string
  count: number
}

export interface SystemOperationalMetricPoint {
  date: string
  runs_total: number
  runs_success: number
  runs_failed: number
  runs_skipped: number
  run_success_rate: number
  llm_calls: number
  llm_success: number
  llm_failed: number
  llm_success_rate: number
  llm_tokens: number
  llm_cost: number
  push_total: number
  push_success: number
  push_failed: number
  push_success_rate: number
}

export interface SystemDistributionItem {
  name: string
  count: number
  percent: number
}

export type DeploymentReadinessStatus = 'PASS' | 'WARN' | 'FAIL' | string
export type DeploymentReadinessLevel = 'READY' | 'NEEDS_ATTENTION' | 'BLOCKED' | string

export interface DeploymentReadinessItem {
  category: string
  code: string
  title: string
  status: DeploymentReadinessStatus
  severity: 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string
  description: string
  evidence?: string
  action?: string
}

export interface DeploymentReadinessCategory {
  code: string
  name: string
  status: DeploymentReadinessStatus
  score: number
  summary: string
  passed: number
  warnings: number
  blockers: number
  items: DeploymentReadinessItem[]
}

export interface DeploymentReadiness {
  generated_at: string
  readiness_score: number
  readiness_level: DeploymentReadinessLevel
  production_ready: boolean
  summary: string
  passed: number
  warnings: number
  blockers: number
  total_items: number
  top_actions: DeploymentReadinessItem[]
  categories: DeploymentReadinessCategory[]
  latest_run?: {
    run_id?: string | null
    status?: string | null
    started_at?: string | null
    finished_at?: string | null
    total_raw?: number
    total_events?: number
  }
  config_summary?: Record<string, any>
}

export interface SystemMetrics {
  generated_at: string
  today: string
  summary: {
    system_score: number
    total_events: number
    today_events: number
    high_risk_count: number
    fallback_sample_count: number
    avg_credibility: number
    enabled_sources: number
    healthy_sources: number
    down_sources: number
    source_success_rate: number
    model_success_rate: number
    avg_llm_latency_ms: number
    llm_calls_24h: number
    llm_success_24h: number
    llm_failed_24h: number
    llm_tokens_24h: number
    llm_tokens_7d: number
    llm_cost_24h: number
    llm_cost_7d: number
    runs_7d: number
    run_success_7d: number
    run_failed_7d: number
    run_success_rate_7d: number
    avg_run_duration_seconds: number
    rag_hit_rate: number
    push_success_rate: number
    push_success_count: number
    push_failed_count: number
    push_skipped_count: number
    logs_total: number
    errors_24h: number
    warnings_24h: number
    feedback_positive_count?: number
    feedback_negative_count?: number
    feedback_blocked_count?: number
    feedback_favorite_count?: number
    feedback_total_count?: number
    feedback_positive_rate?: number
  }
  trends: {
    events_7d: SystemMetricPoint[]
    briefings_7d: SystemMetricPoint[]
    operations_7d: SystemOperationalMetricPoint[]
  }
  distributions: {
    category: SystemDistributionItem[]
    source: SystemDistributionItem[]
  }
  source_health: Record<string, any>
  llm: Record<string, any>
  push: Record<string, any>
  logs: {
    total: number
    errors_24h: number
    warnings_24h: number
    latest_error?: SystemLogItem | null
    level_counts: Record<string, number>
    module_counts: Array<{ module: string; count: number }>
    recent: SystemLogItem[]
  }
  feedback?: {
    counts?: Partial<Record<EventFeedbackAction, number>>
    positive_count?: number
    negative_count?: number
    blocked_count?: number
    favorite_count?: number
    total_count?: number
    positive_rate?: number
  }
  recent_runs: AgentRun[]
  last_briefing?: {
    briefing_date?: string
    title?: string
    status?: string
    updated_at?: string
  }
}

export interface KnowledgeDocument {
  id: number
  title: string
  source?: string
  tags?: string[]
  chunk_count: number
  status: string
  error_message?: string
  content?: string
  created_at?: string
  updated_at?: string
}

export interface KnowledgeChunk {
  id: number
  document_id: number
  chunk_index: number
  title?: string
  content: string
  token_count: number
  vector_id?: string
  embedding_model?: string
  embedding_dim?: number
  metadata?: Record<string, any>
  created_at?: string
}

export interface KnowledgeIngestRun {
  id: number
  document_id?: number
  document_title?: string
  document_source?: string
  status: 'QUEUED' | 'PARSING' | 'CHUNKING' | 'EMBEDDING' | 'VECTOR_UPSERT' | 'RUNNING' | 'SUCCESS' | 'FAILED' | string
  chunk_count: number
  embedding_model?: string
  vector_collection?: string
  error_message?: string
  started_at?: string
  finished_at?: string
  duration_ms?: number
}

export interface KnowledgeEmbeddingTestResult {
  ok: boolean
  provider: string
  model: string
  dimension: number
  configured_dimension: number
  latency_ms: number
  fallback: boolean
  error_message?: string
}

export interface KnowledgeSearchResult {
  chunk_id: number
  document_id: number
  document_title: string
  chunk_index: number
  content: string
  score: number
  source?: string
  metadata?: Record<string, any>
}

export interface KnowledgeAskResult {
  question: string
  answer: string
  mode: 'LLM_RAG' | 'RULE_RAG' | 'NO_CONTEXT' | 'DIRECT_REPLY' | string
  model?: string
  error?: string
  references: KnowledgeSearchResult[]
  skipped_retrieval?: boolean
  intent?: string
  route_reason?: string
  latest_question?: string
}

export interface KnowledgeStreamEvent {
  type: 'meta' | 'delta' | 'done' | 'error' | string
  content?: string
  mode?: 'LLM_RAG' | 'RULE_RAG' | 'NO_CONTEXT' | 'DIRECT_REPLY' | string
  model?: string
  error?: string
  message?: string
  references?: KnowledgeSearchResult[]
  skipped_retrieval?: boolean
  intent?: string
  route_reason?: string
  latest_question?: string
}
