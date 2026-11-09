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
  await expect(page.getByTestId('plan-row-0')).toContainText('运行中')
  await expect(page.getByTestId('plan-item-code-0')).toBeDisabled()

  await page.getByTestId('plan-disarm').click()
  await expect(page.getByTestId('plan-status')).toContainText('已取消')
  await expect(page.getByTestId('plan-disarm')).toBeHidden()
  await expect(page.getByTestId('plan-clear')).toBeVisible()
  // Terminal results stay visible instead of falling back to the stale draft.
  await expect(page.getByTestId('plan-result-0')).toContainText('计划已被手动取消')
  await page.getByTestId('plan-edit').click()
  await expect(page.getByTestId('plan-item-code-0')).toBeEnabled()
})

test('real confirmation lists every item and sends the reviewed versions', async ({ page }) => {
  await open(page, '/plan', 'empty')
  const firstAt = at(40)
  const secondAt = at(130)
  await addItem(page, 0, { code: 'AAAA01', amount: '123.45', at: firstAt })
  await addItem(page, 1, { code: 'BBBB02', amount: '678.90', at: secondAt, mode: 'redemption' })
  await page.getByTestId('plan-save').click()
  await page.getByTestId('plan-start').click()
  const confirm = page.getByTestId('plan-confirm')
  const items = confirm.getByTestId('plan-confirm-items').getByRole('listitem')
  await expect(items).toHaveCount(2)
  await expect(items.nth(0)).toContainText('AAAA01 · ¥ 123.45')
  await expect(items.nth(0)).toContainText(`${firstAt.replace('T', ' ')}:00`)
  await expect(items.nth(1)).toContainText('BBBB02 · ¥ 678.90')
  await expect(items.nth(1)).toContainText(`${secondAt.replace('T', ' ')}:00`)
  await expect(confirm.getByRole('button', { name: '确认真实支付' })).toBeDisabled()
  await confirm.getByTestId('plan-confirm-check').click()
  const sent = page.waitForRequest((request) => request.url().endsWith('/api/plan/start'))
  await confirm.getByRole('button', { name: '确认真实支付' }).click()
  expect((await sent).postDataJSON()).toMatchObject({
    plan_id: expect.any(String),
    content_revision: expect.any(String),
    settings_revision: 'mock-revision',
    confirm_real_payment: true,
  })
  await expect(page.getByTestId('plan-status')).toContainText('运行中')
})

test('confirmation of an older plan cannot start its replacement', async ({ page }) => {
  await open(page, '/plan', 'plan')
  await page.getByTestId('plan-start').click()
  const confirm = page.getByTestId('plan-confirm')
  await expect(confirm.getByTestId('plan-confirm-items')).toContainText('JX040229')
  const replacementAt = at(60)
  await page.evaluate(async (purchaseAt) => {
    await fetch('/api/plan', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dry_run: true,
        items: [{ code: 'NEW001', amount: '10', at: `${purchaseAt}:00`, mode: 'first_launch' }],
      }),
    })
  }, replacementAt)
  await expect(confirm.getByTestId('plan-confirm-items')).not.toContainText('NEW001')
  await confirm.getByRole('button', { name: '开始演练' }).click()
  await expect(page.getByText('计划内容或值守配置已变化', { exact: false })).toBeVisible()
  await expect(page.getByTestId('plan-status')).toContainText('待开始')
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
  await expect(page.getByTestId('plan-row-0')).toContainText('运行中')
  await expect(page.getByTestId('plan-row-1')).toContainText('待开始')
  await expect(page.getByTestId('plan-add')).toBeDisabled()
  await expect(page.getByTestId('plan-item-at-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-mode-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-code-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-amount-0')).toBeDisabled()
  await expect(page.getByTestId('plan-item-remove-0')).toBeHidden()
  await expect(page.getByTestId('plan-save')).toBeHidden()
})

test('plan whose window passed shows the expired status', async ({ page }) => {
  await open(page, '/plan', 'plan-expired')
  await expect(page.getByTestId('plan-status')).toContainText('已过期')
  await expect(page.getByTestId('plan-row-0')).toContainText('已过期')
  await expect(page.getByTestId('plan-start')).toBeDisabled()
})

test('plan page switches between continuous timeline and a 7-day week', async ({ page }) => {
  await open(page, '/plan', 'plan')
  await expect(page.getByTestId('plan-timeline')).toBeVisible()
  await expect(page.getByRole('radio', { name: '时间线' })).toBeChecked()

  await page.getByRole('radio', { name: '周视图' }).click()
  const week = page.getByTestId('plan-week')
  await expect(week).toBeVisible()
  await expect(page.getByTestId('plan-week-day-0')).toHaveAttribute('data-today', 'true')
  const firstRange = await week.getByText(/–/).first().textContent()
  await page.getByTestId('plan-week-next').click()
  await expect(week.getByText(/–/).first()).not.toHaveText(firstRange ?? '')
  await page.getByTestId('plan-week-today').click()
  await expect(week.getByText(/–/).first()).toHaveText(firstRange ?? '')

  // The week columns must fit without an inner scrollbar.
  const overflow = await week.evaluate((el) => ({
    x: el.scrollWidth - el.clientWidth,
    y: el.scrollHeight - el.clientHeight,
  }))
  expect(overflow.x).toBeLessThanOrEqual(0)
  expect(overflow.y).toBeLessThanOrEqual(0)
})

test('an unsaved plan draft survives switching sidebar menus', async ({ page }) => {
  await open(page, '/plan', 'empty')
  await addItem(page, 0, { code: 'JX040229', amount: '5000', at: at(40) })
  // The view switch is page-local state too; both it and the draft must come back.
  await page.getByRole('radio', { name: '周视图' }).click()
  await expect(page.getByTestId('plan-week')).toBeVisible()

  await page.getByRole('link', { name: '状态' }).click()
  await expect(page.getByRole('heading', { level: 1, name: '状态' })).toBeVisible()
  // Kept pages are hidden with `display: none`, not just covered by the new page.
  await expect(page.getByTestId('plan-week')).toBeHidden()

  await page.getByRole('link', { name: '计划' }).click()
  await expect(page.getByRole('heading', { level: 1, name: '计划' })).toBeVisible()
  await expect(page.getByRole('radio', { name: '周视图' })).toBeChecked()
  await page.getByRole('radio', { name: '时间线' }).click()
  await expect(page.getByTestId('plan-item-code-0')).toHaveValue('JX040229')
  await expect(page.getByTestId('plan-item-amount-0')).toHaveValue('5000')
})

test('the tasks focus view keeps a kept page mounted behind it', async ({ page }) => {
  await open(page, '/plan', 'armed')
  await page.getByTestId('plan-add').click()
  await page.getByTestId('plan-item-code-0').fill('JX040229')

  await page.getByRole('link', { name: '任务' }).click()
  await expect(page.getByTestId('live')).toBeVisible()
  await page.getByRole('link', { name: '计划' }).click()
  await expect(page.getByTestId('plan-item-code-0')).toHaveValue('JX040229')
})

test('finished plan keeps per-item results and can be copied into a draft', async ({ page }) => {
  await open(page, '/plan', 'plan-done')
  await expect(page.getByTestId('plan-status')).toContainText('已完成')
  await expect(page.getByTestId('plan-result-0')).toContainText('交易委托已接受')
  await expect(page.getByTestId('plan-result-1')).toContainText('窗口内没有买到')
  // Execution results are not an editable form until the user asks to copy.
  await expect(page.getByTestId('plan-item-code-0')).toHaveCount(0)
  await page.getByTestId('plan-edit').click()
  await expect(page.getByTestId('plan-item-code-0')).toBeEnabled()
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
  await page.getByTestId('favorite-settings-AB1234').click()
  const config = page.getByTestId('favorite-settings-dialog')
  await config.getByTestId('test-item-check').check()
  await config.getByTestId('test-amount-input').fill('0.02')
  await config.getByTestId('save-favorite-settings').click()

  await page.getByRole('link', { name: '计划' }).click()
  await page.getByTestId('plan-add').click()
  const row = page.getByTestId('plan-row-0')
  const chip = row.getByTestId('favorite-AB1234')
  await expect(chip).toContainText('测试 ¥0.02')
  await chip.click()
  await expect(page.getByTestId('plan-item-code-0')).toHaveValue('AB1234')
  await expect(page.getByTestId('plan-item-amount-0')).toHaveValue('0.02')
})
