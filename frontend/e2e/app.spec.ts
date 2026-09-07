import { E2E_SESSION_TOKEN, expect, openAuthenticated, test } from './support/app-fixture'

for (const width of [1440, 375]) {
  test(`Registration preserves login layout and completes ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    let registration: any
    await page.route('**/api/auth/register', async route => {
      registration = route.request().postDataJSON()
      await route.fulfill({ status: 201, json: { ok: true, message: '注册成功，请登录。' } })
    })
    await page.goto('/')
    await expect(page.locator('.split-login-page')).toBeVisible()
    await page.getByRole('tab', { name: '新席位注册' }).click()
    await page.getByLabel('注册账号', { exact: true }).fill('reader_demo')
    await page.getByLabel('用户昵称', { exact: true }).fill('测试读者')
    await page.getByLabel('设置密码', { exact: true }).fill('reader-password')
    await page.getByLabel('确认密码', { exact: true }).fill('reader-password')
    await page.screenshot({ path: `../output/playwright/registration-${width}.png`, fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.getByRole('button', { name: '注册账号', exact: true }).click()
    await expect(page.getByRole('heading', { name: '账号登录' })).toBeVisible()
    await expect(page.getByRole('alert')).toContainText('创建成功')
    expect(registration).toMatchObject({ username: 'reader_demo', password: 'reader-password' })
    expect(await page.evaluate(() => localStorage.getItem('HOTSPOT_ADMIN_TOKEN'))).toBeNull()
  })
}

test('Member navigation excludes management and handles stale default page', async ({ page, apiState }) => {
  await page.addInitScript(() => localStorage.setItem('hotspot_default_page', 'models'))
  await page.route('**/api/auth/me', route => route.fulfill({ json: { data: {
    username: 'reader', display_name: '测试读者', role: 'user', is_admin: false,
    avatar_text: '读者', permissions: ['events:read', 'feedback:write'], auth_mode: 'password', api_auth_enabled: true,
  } } }))
  await openAuthenticated(page)
  for (const name of ['用户管理', '模型配置', '专题知识库', '数据看板', '生成今日早报', '写入知识库']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  await expect(page.locator('.setup-nudge')).toHaveCount(0)
  expect(apiState.requests.filter(request => /^\/(models|knowledge|system)\//.test(request.path))).toEqual([])
  await page.getByRole('button', { name: '个人中心', exact: true }).click()
  await expect(page.locator('.role-badge')).toHaveText('普通用户')
  await expect(page.getByRole('button', { name: '开发者凭据' })).toHaveCount(0)
})

test('Administrator searches users, toggles status and resets password', async ({ page }) => {
  const user = { id: 2, username: 'reader_demo', display_name: '测试读者', role: 'user', is_active: true, created_at: '2026-09-07T08:00:00' }
  let resetPayload: any
  await page.route('**/api/auth/users**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { data: { items: [user], total: 1, page: 1, page_size: 20 } } })
    if (route.request().method() === 'PATCH') {
      user.is_active = route.request().postDataJSON().is_active
      return route.fulfill({ json: { data: user } })
    }
    resetPayload = route.request().postDataJSON()
    return route.fulfill({ json: { ok: true } })
  })
  await openAuthenticated(page)
  await page.getByRole('button', { name: '用户管理', exact: true }).click()
  await page.getByLabel('搜索账号或昵称').fill('reader')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  const row = page.getByRole('row').filter({ hasText: 'reader_demo' })
  await row.getByRole('button', { name: '停用', exact: true }).click()
  await expect(row.getByRole('button', { name: '启用', exact: true })).toBeVisible()
  await row.getByRole('button', { name: '重置密码', exact: true }).click()
  const form = page.locator('form').filter({ has: page.getByLabel('确认密码', { exact: true }) })
  await form.getByLabel('新密码', { exact: true }).fill('reset-password')
  await form.getByLabel('确认密码', { exact: true }).fill('reset-password')
  await form.getByRole('button', { name: '保存', exact: true }).click()
  await expect(form).toHaveCount(0)
  expect(resetPayload).toEqual({ new_password: 'reset-password', confirm_password: 'reset-password' })
  await page.screenshot({ path: '../output/playwright/users-management.png', fullPage: true })
})

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
  await expect(page.getByRole('heading', { name: '账号登录' })).toBeVisible()

  await page.getByLabel('账号', { exact: true }).fill('admin')
  await page.getByLabel('安全密码', { exact: true }).fill('correct-password')
  await page.getByLabel('保持 30 天免登录').check()
  await page.getByRole('button', { name: '进入工作台', exact: true }).click()

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
