import { expect, test as base, type Page, type Route } from '@playwright/test'

export const E2E_SESSION_TOKEN = 'e2e-session-token'

const profile = {
  username: 'admin',
  display_name: 'E2E 管理员',
  role: 'ADMIN',
  avatar_text: 'E2',
  permissions: ['briefing:generate', 'events:read', 'knowledge:manage', 'system:observe', 'config:manage'],
  auth_mode: 'password',
  auth_modes: ['password'],
  api_auth_enabled: true,
  login_security: {
    failed_count: 0,
    failure_limit: 5,
    lock_seconds: 600,
    password_enabled: true,
    password_hash_configured: true,
  },
}

const defaultProvider = {
  id: 1,
  code: 'primary-model',
  name: '主模型通道',
  base_url: 'https://model.example.test/v1',
  api_key: '',
  api_key_masked: 'sk-***test',
  api_key_configured: true,
  uses_env_api_key: false,
  model: 'gpt-e2e',
  priority: 1,
  enabled: true,
  requires_api_key: true,
  timeout_seconds: 30,
  max_tokens: 1200,
  temperature: 0.2,
  input_cost_per_million: 0.5,
  output_cost_per_million: 2,
  note: 'CI fixture',
  last_test_status: 'SUCCESS',
}

const defaultPushConfig = {
  channel: 'qq_bot',
  enabled: false,
  onebot_api_base: 'http://127.0.0.1:3000',
  target_type: 'private',
  user_id: '10001',
  group_id: '',
  access_token: '',
  access_token_masked: 'tok***test',
  retry_times: 2,
  timeout_seconds: 10,
  max_chars: 1800,
  allow_partial_success: true,
}

export interface ApiRequestRecord {
  method: string
  path: string
  authorization: string
  body?: Record<string, unknown>
}

export interface MockApiState {
  requests: ApiRequestRecord[]
  loginAttempts: Array<Record<string, unknown>>
  providers: Array<Record<string, any>>
  pushConfig: Record<string, any>
  savedProvider?: Record<string, unknown>
  testedPush?: Record<string, unknown>
  savedPush?: Record<string, unknown>
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(body),
  })
}

function requestBody(route: Route): Record<string, unknown> {
  try {
    return route.request().postDataJSON() as Record<string, unknown>
  } catch {
    return {}
  }
}

async function installApiMock(page: Page, state: MockApiState) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const path = url.pathname.replace(/^\/api/, '')
    const method = request.method()
    const body = method === 'GET' ? undefined : requestBody(route)

    state.requests.push({
      method,
      path,
      authorization: request.headers().authorization || '',
      body,
    })

    if (method === 'GET' && path === '/auth/options') return json(route, { data: { registration_enabled: true } })
    if (method === 'POST' && path === '/auth/login') {
      state.loginAttempts.push(body || {})
      if (body?.password !== 'correct-password') {
        return json(route, { detail: '管理员账号或密码不正确。' }, 401)
      }
      return json(route, {
        ok: true,
        data: {
          token: E2E_SESSION_TOKEN,
          profile,
          login_at: '2026-07-16T08:00:00Z',
          expires_in: 3600,
        },
      })
    }

    if (method === 'GET' && path === '/auth/me') return json(route, { data: profile })
    if (method === 'POST' && path === '/auth/logout') return json(route, { ok: true, revoked: true })

    if (method === 'GET' && path === '/system/status') {
      return json(route, { data: { status: 'RUNNING', api_auth_enabled: true } })
    }
    if (method === 'GET' && path === '/system/metrics') {
      const dates = ['2026-07-10', '2026-07-11', '2026-07-12', '2026-07-13', '2026-07-14', '2026-07-15', '2026-07-16']
      return json(route, {
        data: {
          generated_at: '2026-07-16T08:00:00Z',
          today: '2026-07-16',
          summary: {
            system_score: 96,
            total_events: 12,
            today_events: 3,
            high_risk_count: 1,
            fallback_sample_count: 0,
            avg_credibility: 91,
            enabled_sources: 2,
            healthy_sources: 2,
            down_sources: 0,
            source_success_rate: 100,
            model_success_rate: 98,
            avg_llm_latency_ms: 320,
            llm_calls_24h: 8,
            llm_success_24h: 8,
            llm_failed_24h: 0,
            llm_tokens_24h: 2400,
            llm_tokens_7d: 12000,
            llm_cost_24h: 0.018,
            llm_cost_7d: 0.091,
            runs_7d: 7,
            run_success_7d: 7,
            run_failed_7d: 0,
            run_success_rate_7d: 100,
            avg_run_duration_seconds: 75,
            rag_hit_rate: 80,
            push_success_rate: 100,
            push_success_count: 5,
            push_failed_count: 0,
            push_skipped_count: 0,
            logs_total: 2,
            errors_24h: 0,
            warnings_24h: 0,
            feedback_positive_count: 4,
            feedback_negative_count: 1,
            feedback_blocked_count: 0,
            feedback_favorite_count: 2,
            feedback_total_count: 5,
            feedback_positive_rate: 80,
          },
          trends: {
            events_7d: dates.map((date, index) => ({ date, count: index + 1 })),
            briefings_7d: dates.map((date) => ({ date, count: 1 })),
            operations_7d: dates.map((date) => ({
              date,
              runs_total: 1,
              runs_success: 1,
              runs_failed: 0,
              runs_skipped: 0,
              run_success_rate: 100,
              llm_calls: 2,
              llm_success: 2,
              llm_failed: 0,
              llm_success_rate: 100,
              llm_tokens: 500,
              llm_cost: 0.004,
              push_total: 1,
              push_success: 1,
              push_failed: 0,
              push_success_rate: 100,
            })),
          },
          distributions: { category: [], source: [] },
          source_health: {},
          llm: {},
          push: {},
          logs: { total: 2, errors_24h: 0, warnings_24h: 0, level_counts: {}, module_counts: [], recent: [] },
          feedback: { positive_count: 4, negative_count: 1, favorite_count: 2, blocked_count: 0 },
          recent_runs: [],
          last_briefing: {},
        },
      })
    }
    if (method === 'GET' && path === '/system/readiness') {
      return json(route, {
        data: {
          generated_at: '2026-07-16T08:00:00Z',
          readiness_score: 100,
          readiness_level: 'READY',
          production_ready: true,
          summary: 'E2E fixture ready',
          passed: 6,
          warnings: 0,
          blockers: 0,
          total_items: 6,
          top_actions: [],
          categories: [],
          latest_run: { run_id: 'e2e-run', status: 'SUCCESS' },
        },
      })
    }
    if (method === 'GET' && path === '/hotspots/briefings/today') return json(route, { data: null })
    if (method === 'GET' && path === '/hotspots/briefings') return json(route, { data: [] })
    if (method === 'GET' && path === '/hotspots/events') return json(route, { data: [] })
    if (method === 'GET' && path === '/hotspots/runs') return json(route, { data: [] })
    if (method === 'GET' && path === '/hotspots/sources/health') {
      return json(route, {
        data: {
          enabled_sources: 2,
          avg_success_rate: 100,
          down_sources: 0,
          degraded_sources: 0,
          items: [],
        },
      })
    }

    if (method === 'GET' && path === '/knowledge/health') {
      return json(route, { data: { ok: true, status: 'READY', collection: 'hotspot_e2e', data: {} } })
    }
    if (method === 'GET' && path === '/knowledge/documents') return json(route, { data: [] })
    if (method === 'GET' && path === '/knowledge/ingest-runs') return json(route, { data: [] })

    if (method === 'GET' && path === '/models/providers') return json(route, { data: state.providers })
    if (method === 'PUT' && /^\/models\/providers\/\d+$/.test(path)) {
      const providerId = Number(path.split('/').pop())
      state.savedProvider = body
      const saved = {
        ...state.providers.find((provider) => provider.id === providerId),
        ...body,
        id: providerId,
        api_key: undefined,
        api_key_masked: body?.api_key ? 'sk-***ated' : 'sk-***test',
        api_key_configured: true,
      }
      state.providers = state.providers.map((provider) => provider.id === providerId ? saved : provider)
      return json(route, { data: saved })
    }
    if (method === 'POST' && path === '/models/providers') {
      state.savedProvider = body
      const saved = { ...body, id: 2, api_key: undefined, api_key_configured: Boolean(body?.api_key) }
      state.providers.push(saved)
      return json(route, { data: saved })
    }

    if (method === 'GET' && path === '/hotspots/push/config') {
      return json(route, { data: state.pushConfig })
    }
    if (method === 'POST' && path === '/hotspots/push/config/test') {
      state.testedPush = body
      return json(route, { ok: true, message: 'E2E OneBot connected' })
    }
    if (method === 'PUT' && path === '/hotspots/push/config') {
      state.savedPush = body
      state.pushConfig = {
        ...state.pushConfig,
        ...body,
        access_token: undefined,
        access_token_masked: body?.access_token ? 'tok***ated' : state.pushConfig.access_token_masked,
      }
      return json(route, { data: state.pushConfig })
    }

    return json(route, { data: [] })
  })
}

type Fixtures = {
  apiState: MockApiState
}

export const test = base.extend<Fixtures>({
  apiState: [async ({ page }, use) => {
    const state: MockApiState = {
      requests: [],
      loginAttempts: [],
      providers: [{ ...defaultProvider }],
      pushConfig: { ...defaultPushConfig },
    }
    const browserIssues: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error' || message.type() === 'warning') {
        browserIssues.push(`console ${message.type()}: ${message.text()}`)
      }
    })
    page.on('pageerror', (error) => browserIssues.push(`pageerror: ${error.message}`))
    await installApiMock(page, state)
    await use(state)
    expect(browserIssues, '页面不应产生 console warning、console error 或未捕获异常').toEqual([])
  }, { auto: true }],
})

export { expect }

export async function openAuthenticated(page: Page) {
  await page.addInitScript((token) => {
    window.localStorage.setItem('HOTSPOT_ADMIN_TOKEN', token)
  }, E2E_SESSION_TOKEN)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '今日情报', level: 1 })).toBeVisible()
  await expect(page.locator('.global-loading')).toHaveCount(0)
}
