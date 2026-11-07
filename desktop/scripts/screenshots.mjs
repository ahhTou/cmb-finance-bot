// Retakes the README screenshots (docs/images/app-*.png) against the mock backend,
// in WebKit like the Tauri shell on macOS. Never touches the real project or bank app.
// Run from desktop/: pnpm screenshots
import { resolve } from 'node:path'
import { webkit } from '@playwright/test'
import { createServer } from 'vite'

const out = resolve(import.meta.dirname, '../../docs/images')
const shots = [
  ['app-tasks', 'idle', '/tasks'],
  ['app-armed', 'armed', '/tasks'],
  ['app-plan', 'plan', '/plan'],
  ['app-status', 'idle', '/status'],
  ['app-drill', 'idle', '/drill'],
  ['app-settings', 'idle', '/settings'],
  // Dedicated notification tab, connection settings first.
  [
    'app-push',
    'idle',
    '/settings',
    async (page) => {
      await page.getByRole('radio', { name: '推送通知', exact: true }).click()
      await page.getByTestId('push-card').scrollIntoViewIfNeeded()
    },
  ],
  [
    'app-push-options',
    'idle',
    '/settings',
    async (page) => {
      await page.getByRole('radio', { name: '推送通知', exact: true }).click()
      await page.getByTestId('push-preferences').scrollIntoViewIfNeeded()
    },
  ],
]

const selected = new Set(process.argv.slice(2))
const server = await createServer({ mode: 'mock', logLevel: 'silent', server: { port: 5176, strictPort: true } })
await server.listen()
const browser = await webkit.launch()
const page = await browser.newPage({ viewport: { width: 1093, height: 763 }, deviceScaleFactor: 2 })
for (const [name, scenario, path, prepare] of shots) {
  if (selected.size && !selected.has(name)) continue
  await page.goto(`http://localhost:5176/?scenario=${scenario}#${path}`)
  await page.waitForTimeout(2500) // event stream, device/system reads and entrance animations
  if (prepare) {
    await prepare(page)
    await page.waitForTimeout(500)
  }
  await page.screenshot({ path: `${out}/${name}.png` })
  console.log(`${name}.png`)
}
await browser.close()
await server.close()
