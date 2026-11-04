import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `pnpm server` writes the dev backend's port and token here; the proxy adds the
// token so the page itself never needs it in the browser.
function devBackend() {
  try {
    return JSON.parse(readFileSync(resolve(__dirname, '../var/admin-server.json'), 'utf8')) as {
      port: number
      token: string
    }
  } catch {
    return { port: 8765, token: '' }
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    proxy:
      mode === 'mock'
        ? undefined
        : {
            '/api': {
              target: `http://127.0.0.1:${devBackend().port}`,
              configure: (proxy) => {
                proxy.on('proxyReq', (req) => {
                  req.setHeader('Authorization', `Bearer ${devBackend().token}`)
                })
              },
            },
          },
  },
  build: { target: 'safari16', outDir: 'dist' },
}))
