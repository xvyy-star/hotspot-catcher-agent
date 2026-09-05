import { E2E_SESSION_TOKEN, expect, openAuthenticated, test } from './support/app-fixture'

test('Source cutover removes old QA cache without clearing credentials', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('HOTSPOT_KNOWLEDGE_QA_CHAT_V1', 'legacy answer')
    localStorage.setItem('HOTSPOT_KNOWLEDGE_QA_CHAT_V2', 'current answer')
  })
  await openAuthenticated(page)
  expect(await page.evaluate(() => localStorage.getItem('HOTSPOT_KNOWLEDGE_QA_CHAT_V1'))).toBeNull()
  expect(await page.evaluate(() => localStorage.getItem('HOTSPOT_KNOWLEDGE_QA_CHAT_V2'))).toBe('current answer')
  expect(await page.evaluate(() => localStorage.getItem('HOTSPOT_ADMIN_TOKEN'))).toBe(E2E_SESSION_TOKEN)
})

for (const width of [1440, 768, 375, 320]) {
  test(`Official API collection entry ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openAuthenticated(page)
    if (width <= 900) await page.getByRole('button', { name: '打开导航', exact: true }).click()
    await page.getByRole('button', { name: '采集源状态', exact: true }).click()
    const header = await page.locator('.topbar').boundingBox()
    const actions = await page.locator('.topbar > .top-actions').boundingBox()
    expect(actions!.y + actions!.height).toBeLessThanOrEqual(header!.y + header!.height)
    const panel = page.locator('.platform-fetch-panel')
    await expect(panel.getByRole('button', { name: 'GitHub', exact: true })).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Hugging Face', exact: true })).toBeVisible()
    await expect(panel).not.toContainText('B站')
    for (const button of await panel.getByRole('button').all()) {
      const box = await button.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    }
    await page.route('**/api/hotspots/platform-hotspots/fetch', async route => {
      await route.fulfill({ json: { ok: true, data: { sources: {}, total: 0, limit: 20, timeout: 20 } } })
    })
    const pending = page.waitForRequest(request => request.url().includes('/platform-hotspots/fetch'))
    await panel.getByRole('button', { name: '抓取平台系统热点', exact: true }).click()
    expect((await pending).postDataJSON().sources).toEqual(['github', 'huggingface', 'devto'])
    await expect(panel.getByRole('button', { name: '抓取平台系统热点', exact: true })).toBeEnabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    for (const close of await page.getByRole('button', { name: '关闭提示', exact: true }).all()) {
      await close.click()
    }
    await expect(page.locator('.chrome-toast')).toHaveCount(0)
    await page.screenshot({ path: `../output/playwright/official-api-${width}.png`, fullPage: true })
  })
}

test('管理员登录成功后进入工作台并携带会话凭据', async ({ page, apiState }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '管理员身份认证' })).toBeVisible()

  await page.getByLabel('管理员密码').fill('correct-password')
  await page.getByLabel('保持当前浏览器登录状态 (30天)').check()
  await page.getByRole('button', { name: '进入情报中枢', exact: true }).click()

  await expect(page.getByRole('heading', { name: '今日情报', level: 1 })).toBeVisible()
  await expect(page.locator('.global-loading')).toHaveCount(0)
  await expect.poll(() => apiState.requests.filter((request) => request.path === '/system/status').length).toBe(1)
  expect(apiState.loginAttempts).toEqual([
    { username: 'admin', password: 'correct-password', remember: true },
  ])
  expect(await page.evaluate(() => window.localStorage.getItem('HOTSPOT_ADMIN_TOKEN'))).toBe(E2E_SESSION_TOKEN)

  const dashboardRequest = apiState.requests.find((request) => request.path === '/system/status')
  expect(dashboardRequest?.authorization).toBe(`Bearer ${E2E_SESSION_TOKEN}`)
})

test('核心工作区可通过主导航连续切换', async ({ page }) => {
  await openAuthenticated(page)

  for (const pageName of ['数据看板', '热点池', '简报归档', '专题知识库', '知识问答', '今日情报']) {
    await page.getByRole('button', { name: pageName, exact: true }).click()
    await expect(page.getByRole('heading', { name: pageName, level: 1 })).toBeVisible()
    await expect(page.getByRole('button', { name: pageName, exact: true })).toHaveClass(/active/)
    await expect(page.locator('.global-loading')).toHaveCount(0)
  }
})

test('模型配置支持编辑既有通道并保持 Code 不可变', async ({ page, apiState }) => {
  await openAuthenticated(page)
  await page.getByRole('button', { name: '模型配置', exact: true }).click()

  const providerCard = page.locator('.model-card-simple').filter({ hasText: '主模型通道' })
  await expect(providerCard).toBeVisible()
  await providerCard.getByRole('button', { name: '编辑通道' }).click()

  const dialog = page.locator('form').filter({ has: page.locator('#provider-code') })
  await expect(page.getByLabel('Code（唯一标识）')).toBeDisabled()
  await page.getByLabel('通道名称').fill('生产主模型')
  await page.getByLabel('Base URL').fill('https://gateway.example.test/v1')
  await page.getByLabel('API Key 凭据', { exact: true }).fill('sk-e2e-updated')
  await page.getByLabel('当前生效模型 (Model)').fill('gpt-e2e-updated')
  await page.getByLabel('输入单价 (USD / 百万 Token)').fill('1.25')
  await page.getByLabel('输出单价 (USD / 百万 Token)').fill('5')
  await dialog.getByRole('button', { name: '保存配置' }).click()

  await expect(page.getByText('模型通道已保存：生产主模型')).toBeVisible()
  await expect(page.locator('.model-card-simple').filter({ hasText: '生产主模型' })).toBeVisible()
  expect(apiState.savedProvider).toMatchObject({
    id: 1,
    code: 'primary-model',
    name: '生产主模型',
    base_url: 'https://gateway.example.test/v1',
    api_key: 'sk-e2e-updated',
    model: 'gpt-e2e-updated',
    input_cost_per_million: 1.25,
    output_cost_per_million: 5,
  })
})

test('QQ 推送配置支持连通测试与保存', async ({ page, apiState }) => {
  await openAuthenticated(page)
  await page.getByRole('button', { name: 'QQ 推送', exact: true }).click()

  const enabled = page.getByLabel('启用 OneBot 自动推送')
  if (!(await enabled.isChecked())) await enabled.locator('..').click()
  await page.getByLabel('OneBot HTTP API 地址').fill('https://onebot.example.test')
  await page.locator('.radio-pill').filter({ hasText: '群聊消息' }).click()
  await page.getByLabel('群号 QQ').fill('987654321')
  await page.getByLabel('Access Token').fill('token-e2e-updated')

  await page.getByRole('button', { name: '测试连通性', exact: true }).click()
  await expect(page.getByText('连通成功：E2E OneBot connected')).toBeVisible()
  expect(apiState.testedPush).toMatchObject({
    enabled: true,
    onebot_api_base: 'https://onebot.example.test',
    target_type: 'group',
    group_id: '987654321',
    access_token: 'token-e2e-updated',
  })

  await page.getByRole('button', { name: '保存推送配置' }).click()
  await expect(page.getByText('QQ 推送配置已保存')).toBeVisible()
  expect(apiState.savedPush).toMatchObject({
    enabled: true,
    onebot_api_base: 'https://onebot.example.test',
    target_type: 'group',
    group_id: '987654321',
    access_token: 'token-e2e-updated',
  })
  await expect(page.getByLabel('Access Token')).toHaveValue('')
  await expect(page.getByLabel('群号 QQ')).toHaveValue('987654321')
})
