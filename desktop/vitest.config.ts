import { defineConfig } from 'vitest/config'

// Unit tests live next to the source; e2e/ is Playwright-only (`pnpm e2e`).
export default defineConfig({
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
