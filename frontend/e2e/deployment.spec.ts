import { expect, test as base, type Page } from '@playwright/test'

const adminPassword = process.env.PLAYWRIGHT_ADMIN_PASSWORD || ''
const adminUsername = process.env.PLAYWRIGHT_ADMIN_USERNAME?.trim() || 'admin'

type DeploymentFixtures = {
  browserIssues: string[]
}

function redact(value: string): string {
  return adminPassword ? value.split(adminPassword).join('[REDACTED]') : value
}

const test = base.extend<DeploymentFixtures>({
  browserIssues: [async ({ page }, use) => {
    const issues: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error' || message.type() === 'warning') {
        issues.push(redact(`console ${message.type()}: ${message.text()}`))
      }
    })
    page.on('pageerror', (error) => issues.push(redact(`pageerror: ${error.message}`)))
    await use(issues)
    expect(issues, '真实部署页面不应产生 console warning、console error 或未捕获异常').toEqual([])
  }, { auto: true }],
})

test.use({ trace: 'off', screenshot: 'off', video: 'off' })

function apiKey(method: string, pathname: string): string {
  return `${method.toUpperCase()} ${pathname}`
}

async function expectSuccessfulApi(
  statuses: Map<string, number[]>,
  method: string,
  pathname: string,
): Promise<void> {
  const key = apiKey(method, pathname)
  await expect.poll(
    () => statuses.get(key)?.length ?? 0,
    { message: `${key} 应至少返回一次响应` },
  ).toBeGreaterThan(0)
  const observed = statuses.get(key) || []
  expect(
    observed.every((status) => status >= 200 && status < 300),
    `${key} 的全部响应都应为 2xx，实际为 ${observed.join(', ')}`,
  ).toBe(true)
}

async function storedToken(page: Page): Promise<string | null> {
  return page.evaluate(() => window.localStorage.getItem('HOTSPOT_ADMIN_TOKEN'))
}

test('真实部署入口完成登录、数据看板与退出闭环', async ({ page }) => {
  if (!adminPassword) {
    throw new Error('PLAYWRIGHT_ADMIN_PASSWORD is required for deployment E2E')
  }

  const apiStatuses = new Map<string, number[]>()
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (!url.pathname.startsWith('/api/')) return
    const key = apiKey(response.request().method(), url.pathname)
    apiStatuses.set(key, [...(apiStatuses.get(key) || []), response.status()])
  })

  const entryResponse = await page.goto('/')
  expect(entryResponse?.ok(), '真实部署首页应返回 2xx').toBe(true)
  await expect(page.getByRole('heading', { name: '账号登录' })).toBeVisible()

  await page.getByLabel('账号', { exact: true }).fill(adminUsername)
  await page.getByLabel('安全密码', { exact: true }).fill(adminPassword)
  await page.getByRole('button', { name: '进入工作台', exact: true }).click()

  await expect(page.getByRole('heading', { name: '今日情报', level: 1 })).toBeVisible()
  await expect(page.locator('.global-loading')).toHaveCount(0)
  await expect.poll(() => storedToken(page), { message: '登录后应保存会话凭据' }).not.toBeNull()
  await expectSuccessfulApi(apiStatuses, 'POST', '/api/auth/login')
  await expectSuccessfulApi(apiStatuses, 'GET', '/api/system/status')

  await page.getByRole('button', { name: '数据看板', exact: true }).click()
  await expect(page.getByRole('heading', { name: '数据看板', level: 1 })).toBeVisible()
  await expect(page.getByText('24h 模型成本', { exact: true })).toBeVisible()
  await expect(page.locator('.global-loading')).toHaveCount(0)
  await expectSuccessfulApi(apiStatuses, 'GET', '/api/system/metrics')
  await expectSuccessfulApi(apiStatuses, 'GET', '/api/system/readiness')

  await page.getByRole('button', { name: '个人中心', exact: true }).click()
  await expect(page.getByRole('heading', { name: '个人中心', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()

  await expect(page.getByRole('heading', { name: '账号登录' })).toBeVisible()
  await expect.poll(() => storedToken(page), { message: '退出后应清除本地会话凭据' }).toBeNull()
  await expectSuccessfulApi(apiStatuses, 'POST', '/api/auth/logout')
})
