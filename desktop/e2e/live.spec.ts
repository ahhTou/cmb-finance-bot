import { expect, type Page, test } from '@playwright/test'

/**
 * Opens the focus view on the armed mock scenario, the same mock flow as
 * app.spec.ts (see src/mocks/fixtures.ts).
 */
async function openLive(page: Page) {
  await page.goto('/?scenario=armed#/tasks')
  const live = page.getByTestId('live')
  await expect(live).toBeVisible()
  return live
}

/**
 * `blur`/`focus` are dispatched on the window exactly as a real window focus
 * change would; the hook treats the event itself as the new state.
 */
async function dispatchWindowEvent(page: Page, type: 'blur' | 'focus') {
  await page.evaluate((eventType) => window.dispatchEvent(new Event(eventType)), type)
}

test('focus view pauses every animation while the window is inactive', async ({ page }) => {
  const live = await openLive(page)
  const codeRain = live.getByTestId('code-rain')
  const waves = live.getByTestId('waves')
  const phaseDot = live.getByTestId('phase-dot')
  const chain = live.getByTestId('chain-progress')
  const countdown = live.getByTestId('countdown')

  // A freshly opened page is focused: the animation flags are on.
  await expect(live).toHaveAttribute('data-window-active', 'true')
  await expect(codeRain).toHaveAttribute('data-active', 'true')
  await expect(waves).toHaveAttribute('data-active', 'true')
  await expect(phaseDot).toHaveAttribute('data-active', 'true')
  await expect(chain).toHaveAttribute('data-active', 'true')
  await expect(countdown).toHaveAttribute('aria-label', /^\d+:\d{2}$/)

  // Losing the window turns every decoration off, but the countdown, the chain
  // and the status text stay on screen: presentation changes, data does not.
  await dispatchWindowEvent(page, 'blur')
  await expect(live).toHaveAttribute('data-window-active', 'false')
  await expect(codeRain).toHaveAttribute('data-active', 'false')
  await expect(waves).toHaveAttribute('data-active', 'false')
  await expect(phaseDot).toHaveAttribute('data-active', 'false')
  await expect(chain).toHaveAttribute('data-active', 'false')
  await expect(chain).toBeVisible()
  await expect(live.getByText('盯盘中')).toBeVisible()
  await expect(countdown).toBeVisible()
  await expect(countdown).toHaveAttribute('aria-label', /^\d+:\d{2}$/)
  await expect(live.getByRole('button', { name: '终止布防' })).toBeEnabled()

  // Refocusing switches the animations back on immediately.
  await dispatchWindowEvent(page, 'focus')
  await expect(live).toHaveAttribute('data-window-active', 'true')
  await expect(codeRain).toHaveAttribute('data-active', 'true')
  await expect(waves).toHaveAttribute('data-active', 'true')
  await expect(phaseDot).toHaveAttribute('data-active', 'true')
  await expect(chain).toHaveAttribute('data-active', 'true')
  await expect(countdown).toBeVisible()
})
