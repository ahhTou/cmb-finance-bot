import { expect, type Page, test } from '@playwright/test'

/** Opens a page of the app on a mock scenario (see src/mocks/fixtures.ts). */
async function open(page: Page, path: string, scenario = 'idle') {
  await page.goto(`/?scenario=${scenario}#${path}`)
}

test('sidebar switches pages and remembers the last one', async ({ page }) => {
  await open(page, '/tasks')
  await expect(page.getByRole('heading', { level: 1, name: '任务' })).toBeVisible()
  for (const name of ['状态', '演练', '收藏', '历史', '设置']) {
    await page.getByRole('link', { name }).click()
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  }
  await page.goto('/?scenario=idle#/')
  await expect(page.getByRole('heading', { level: 1, name: '设置' })).toBeVisible()
})

test('tasks page shows modes and the last ended task', async ({ page }) => {
  await open(page, '/tasks')
  const first = page.getByTestId('mode-first_launch')
  await expect(first.getByText('可用')).toBeVisible()
  await expect(first.getByText('上次任务已结束 · 已取消')).toBeVisible()
  await expect(page.getByTestId('mode-pickup').getByRole('button', { name: '敬请期待' })).toBeDisabled()
})

test('drill arm goes through confirm and switches to the live view', async ({ page }) => {
  await open(page, '/tasks', 'empty')
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('如 JX040229').fill('JX040229')
  await dialog.getByPlaceholder('上限 50000 元').fill('0.01')
  await dialog.getByRole('switch').first().click() // 演练
  await dialog.getByRole('switch').nth(1).click() // 立即排练
  await dialog.getByRole('button', { name: '下一步' }).click()
  await expect(dialog.getByText(/约三分钟后 演练到输完密码 0\.01 元/)).toBeVisible()
  await dialog.getByRole('button', { name: '开始演练' }).click()
  await expect(page.getByTestId('live')).toBeVisible()
  await expect(page.getByTestId('countdown')).toHaveAttribute('aria-label', /^0[23]:\d\d$/)
})

test('real arm needs the amount typed again', async ({ page }) => {
  await open(page, '/tasks', 'empty')
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('如 JX040229').fill('JX040229')
  await dialog.getByPlaceholder('上限 50000 元').fill('100')
  await dialog.getByRole('button', { name: '下一步' }).click()
  const confirm = dialog.getByRole('button', { name: '确认真实布防' })
  await expect(confirm).toBeDisabled()
  await dialog.getByTestId('confirm-amount').fill('10')
  await expect(confirm).toBeDisabled()
  await dialog.getByTestId('confirm-amount').fill('100')
  await expect(confirm).toBeEnabled()
})

test('invalid input is reported in the toast', async ({ page }) => {
  await open(page, '/tasks', 'empty')
  await page.getByTestId('mode-redemption').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('如 JX040229').fill('x')
  await dialog.getByRole('button', { name: '下一步' }).click()
  await expect(page.getByRole('alert')).toContainText('产品代码须为 4–20 位字母或数字。')
})

test('an active task shows the live view and can be stopped', async ({ page }) => {
  await open(page, '/tasks', 'armed')
  const live = page.getByTestId('live')
  await expect(live).toBeVisible()
  await expect(live.getByText('JX040229', { exact: true })).toBeVisible()
  await live.getByRole('button', { name: '终止布防' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '确认终止' }).click()
  await expect(live).toBeHidden()
  await expect(page.getByRole('heading', { level: 1, name: '任务' })).toBeVisible()
})

test('firing disables stopping', async ({ page }) => {
  await open(page, '/tasks', 'firing')
  await expect(page.getByTestId('countdown')).toHaveAttribute('aria-label', '00:00')
  await expect(page.getByRole('button', { name: '终止布防' })).toBeDisabled()
})

test('status page fills every card', async ({ page }) => {
  await open(page, '/status')
  await expect(page.getByTestId('card-mac').getByText('0.087 秒')).toBeVisible()
  await expect(page.getByTestId('card-emulator').getByText('运行中')).toBeVisible()
  await expect(page.getByTestId('card-credentials').getByText('已设置')).toBeVisible()
  await page.getByTestId('card-screen').getByRole('button', { name: '截图' }).click()
  await expect(page.getByTestId('card-screen').getByRole('img', { name: '模拟器画面' })).toBeVisible()
})

test('backend failure shows in the toast and can be dismissed', async ({ page }) => {
  await open(page, '/tasks', 'error')
  const toast = page.getByRole('alert')
  await expect(toast).toContainText('后端返回格式无效。')
  await toast.getByRole('button', { name: '关闭提示' }).click()
  await expect(toast).toBeHidden()
})

test('favorites add, rename and fill the arm form', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await expect(page.getByLabel('AB1234 标题')).toHaveValue('测试产品')
  await page.getByRole('link', { name: '任务' }).click()
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  await page.getByRole('dialog').getByRole('button', { name: '测试产品' }).click()
  await expect(page.getByRole('dialog').getByPlaceholder('如 JX040229')).toHaveValue('AB1234')
})

test('history lists records and shows details', async ({ page }) => {
  await open(page, '/history')
  await expect(page.getByText('窗口内无额度')).toBeHidden()
  await page.getByRole('button', { name: /JX040229/ }).click()
  await expect(page.getByText('窗口内无额度')).toBeVisible()
  await expect(page.getByText('模拟器重启后恢复', { exact: false })).toBeVisible()
})

test('drill buy shows command output', async ({ page }) => {
  await open(page, '/drill')
  await page.getByPlaceholder('如 JX040229').first().fill('JX040229')
  await page.getByRole('button', { name: '单笔购买演练' }).click()
  await expect(page.getByRole('dialog', { name: '命令输出' })).toContainText('输完密码，未点确定，演练结束')
})

test('pages fit the minimum window without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 940, height: 680 })
  for (const path of ['/tasks', '/status', '/drill', '/favorites', '/history', '/settings']) {
    await open(page, path)
    await expect(page.locator('main')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    expect(overflow, path).toBeLessThanOrEqual(0)
  }
})

test('while armed, other pages stay reachable and the sidebar shows the task', async ({ page }) => {
  await open(page, '/tasks', 'armed')
  await expect(page.getByTestId('live')).toBeVisible()
  await page.getByRole('link', { name: '状态' }).click()
  await expect(page.getByRole('heading', { level: 1, name: '状态' })).toBeVisible()
  const bubble = page.getByRole('navigation').getByTestId('watch-bubble')
  await expect(bubble).toContainText('JX040229')
  await bubble.click()
  await expect(page.getByTestId('live')).toBeVisible()
  await expect(bubble).toBeHidden()
})

test('focus view shows the purchase chain and follows the running step', async ({ page }) => {
  await open(page, '/tasks', 'progress')
  const chain = page.getByTestId('chain-progress')
  await expect(chain).toBeVisible()
  const running = chain.locator('[aria-current="step"]')
  await expect(running).toHaveText('P3', { timeout: 10_000 })
  await expect(chain).toContainText('冷启动登录')
  await expect(running).toHaveText('P7', { timeout: 20_000 })
  await expect(chain).toContainText('到点查询与重试')
  await expect(chain).toContainText('fired_at')
})
