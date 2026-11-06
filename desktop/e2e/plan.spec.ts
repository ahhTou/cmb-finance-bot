import { expect, type Page, test } from '@playwright/test'

/** Opens a page of the app on a mock scenario (see src/mocks/fixtures.ts). */
async function open(page: Page, path: string, scenario = 'empty') {
  await page.goto(`/?scenario=${scenario}#${path}`)
}

const pad = (value: number) => String(value).padStart(2, '0')

/** A future <input type="datetime-local"> value; seconds are dropped. */
function at(minutesFromNow: number) {
  const date = new Date(Date.now() + minutesFromNow * 60_000)
  date.setSeconds(0, 0)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

interface Draft {
  code: string
  amount: string
  at: string
  mode?: 'first_launch' | 'redemption'
}

/** Clicks 「添加布防」 and fills the new row at `index`. */
async function addItem(page: Page, index: number, item: Draft) {
  await page.getByTestId('plan-add').click()
  await page.getByTestId(`plan-item-at-${index}`).fill(item.at)
  await page.getByTestId(`plan-item-code-${index}`).fill(item.code)
  await page.getByTestId(`plan-item-amount-${index}`).fill(item.amount)
  if (item.mode) await page.getByTestId(`plan-item-mode-${index}`).selectOption(item.mode)
}

test('sidebar shows the plan page between tasks and status', async ({ page }) => {
  await page.goto('/?scenario=plan#/tasks')
  const links = page.getByRole('navigation').getByRole('link')
  await expect(links).toHaveText(['任务', '计划', '状态', '演练', '收藏', '历史', '设置'])
  await links.filter({ hasText: '计划' }).click()
  await expect(page.getByRole('heading', { level: 1, name: '计划' })).toBeVisible()
  await expect(page.getByTestId('plan-status')).toContainText('待开始')
  await expect(page.getByTestId('plan-row-1')).toBeVisible()
  await expect(page.getByTestId('plan-item-code-1')).toHaveValue('133045A')
})

test('empty plan: add two items, save, start a drill, then cancel', async ({ page }) => {
  await open(page, '/plan', 'empty')
  await expect(page.getByTestId('plan-status')).toContainText('未计划')

  await addItem(page, 0, { code: 'JX040229', amount: '5000', at: at(40) })
  await addItem(page, 1, { code: '133045A', amount: '20000', at: at(130), mode: 'redemption' })

  // 演练计划 switch: the drill run needs no real-payment confirmation.
  await page.getByRole('switch').click()
  await expect(page.getByRole('switch')).toBeChecked()
  await page.getByTestId('plan-save').click()

  // The backend fills prep_at / end_at, so each row shows the computed schedule.
  const first = page.getByTestId('plan-row-0')
  await expect(first).toContainText('冷启动')
  await expect(first).toContainText('预计结束')
  await expect(page.getByTestId('plan-status')).toContainText('待开始')

  await page.getByTestId('plan-start').click()
  const confirm = page.getByTestId('plan-confirm')
  await expect(confirm).toContainText('2 项')
  await expect(confirm).toContainText('25,000.00')
  await confirm.getByRole('button', { name: '开始演练' }).click()

  await expect(page.getByTestId('plan-status')).toContainText('运行中')
  await expect(page.getByTestId('plan-row-0')).toContainText('执行中')
  await expect(page.getByTestId('plan-item-code-0')).toBeDisabled()

  await page.getByTestId('plan-disarm').click()
  await expect(page.getByTestId('plan-status')).toContainText('已取消')
  await expect(page.getByTestId('plan-disarm')).toBeHidden()
  await expect(page.getByTestId('plan-clear')).toBeVisible()
})

test('backend problems disable the start button', async ({ page }) => {
  await open(page, '/plan', 'empty')
  await addItem(page, 0, { code: 'JX040229', amount: '1000', at: at(40) })
  await addItem(page, 1, { code: '133045A', amount: '1000', at: at(42) })
  await page.getByTestId('plan-save').click()

  const problems = page.getByTestId('plan-problems')
  await expect(problems).toBeVisible()
  await expect(problems).toContainText('间隔太近')
  await expect(page.getByTestId('plan-start')).toBeDisabled()
})

test('a running plan is read-only', async ({ page }) => {
  await open(page, '/plan', 'plan')
  await expect(page.getByTestId('plan-status')).toContainText('待开始')
  await page.getByTestId('plan-start').click()
  await page.getByTestId('plan-confirm').getByRole('button', { name: '开始演练' }).click()

  await expect(page.getByTestId('plan-status')).toContainText('运行中')
  await expect(page.getByTestId('plan-row-0')).toContainText('执行中')
  await expect(page.getByTestId('plan-row-1')).toContainText('待执行')
  await expect(page.getByTestId('plan-add')).toBeDisabled()
  await expect(page.getByTestId('plan-item-at-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-mode-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-code-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-amount-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-remove-0')).toBeHidden()
  await expect(page.getByTestId('plan-save')).toBeHidden()
})

test('plan page fits the minimum window', async ({ page }) => {
  await page.setViewportSize({ width: 940, height: 680 })
  await open(page, '/plan', 'plan')
  await expect(page.getByTestId('plan-row-1')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('favorite chips fill the product code in a plan row', async ({ page }) => {
  await open(page, '/plan', 'idle')
  await page.getByTestId('plan-add').click()
  const row = page.getByTestId('plan-row-0')
  await expect(row.getByTestId('favorite-JX040229')).toBeVisible()
  await row.getByTestId('favorite-JX040229').click()
  await expect(page.getByTestId('plan-item-code-0')).toHaveValue('JX040229')
  // A plain favourite has no amount, so the amount field stays untouched.
  await expect(page.getByTestId('plan-item-amount-0')).toHaveValue('')
})

test('the test favourite fills code and amount in a plan row', async ({ page }) => {
  // Create one favourite and mark it as the drill test item first.
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('set-test-AB1234').click()
  const config = page.getByRole('dialog')
  await config.getByTestId('test-amount-input').fill('0.02')
  await config.getByRole('button', { name: '保存测试项' }).click()

  await page.getByRole('link', { name: '计划' }).click()
  await page.getByTestId('plan-add').click()
  const row = page.getByTestId('plan-row-0')
  const chip = row.getByTestId('favorite-AB1234')
  await expect(chip).toContainText('测试 ¥0.02')
  await chip.click()
  await expect(page.getByTestId('plan-item-code-0')).toHaveValue('AB1234')
  await expect(page.getByTestId('plan-item-amount-0')).toHaveValue('0.02')
})
