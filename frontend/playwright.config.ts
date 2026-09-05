import { defineConfig, devices } from '@playwright/test'

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL?.trim()
const baseURL = externalBaseURL || 'http://127.0.0.1:4177'
const outputName = externalBaseURL ? 'deployment' : 'e2e'

export default defineConfig({
  testDir: './e2e',
  testIgnore: externalBaseURL ? [] : ['**/deployment.spec.ts'],
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['line'],
    ['html', { outputFolder: `../output/playwright/${outputName}-report`, open: 'never' }],
  ],
  outputDir: `../output/playwright/${outputName}-results`,
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : undefined,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: externalBaseURL
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 4177',
        url: 'http://127.0.0.1:4177',
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
})
