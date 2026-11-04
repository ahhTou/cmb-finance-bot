import { defineConfig, devices } from '@playwright/test'

// Runs against the mock backend only; never touches the real project or bank app.
// WebKit is what the Tauri shell renders with on macOS, Chromium is the dev browser.
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5174',
    viewport: { width: 1093, height: 763 },
    colorScheme: 'dark',
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'webkit', use: { ...devices['Desktop Safari'], viewport: { width: 1093, height: 763 } } },
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1093, height: 763 } } },
  ],
  webServer: {
    command: 'pnpm exec vite --mode mock --port 5174 --strictPort',
    url: 'http://localhost:5174',
    reuseExistingServer: !process.env.CI,
  },
})
