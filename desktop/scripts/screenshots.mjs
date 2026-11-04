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
  ['app-status', 'idle', '/status'],
  ['app-drill', 'idle', '/drill'],
  ['app-settings', 'idle', '/settings'],
]

const server = await createServer({ mode: 'mock', logLevel: 'silent', server: { port: 5176, strictPort: true } })
await server.listen()
const browser = await webkit.launch()
const page = await browser.newPage({ viewport: { width: 1093, height: 763 }, deviceScaleFactor: 2 })
for (const [name, scenario, path] of shots) {
  await page.goto(`http://localhost:5176/?scenario=${scenario}#${path}`)
  await page.waitForTimeout(2500) // event stream, device/system reads and entrance animations
  await page.screenshot({ path: `${out}/${name}.png` })
  console.log(`${name}.png`)
}
await browser.close()
await server.close()
