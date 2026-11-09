import { expect, type Locator, type Page, test } from '@playwright/test'

/** Opens a page of the app on a mock scenario (see src/mocks/fixtures.ts). */
async function open(page: Page, path: string, scenario = 'idle') {
  await page.goto(`/?scenario=${scenario}#${path}`)
}

/** Every scrollable region under `root` that would draw a scrollbar. */
async function scrollbarsIn(root: Locator) {
  return root.evaluate((node) => {
    const found: string[] = []
    const walk = (el: Element) => {
      const style = getComputedStyle(el)
      const vertical =
        (style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight - el.clientHeight > 1
      const horizontal =
        (style.overflowX === 'auto' || style.overflowX === 'scroll') && el.scrollWidth - el.clientWidth > 1
      if (vertical || horizontal)
        found.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 80)}`)
      for (const child of el.children) walk(child)
    }
    walk(node)
    return found
  })
}

/**
 * Opens /history and scrolls to the complete-history screen. The page is exactly
 * two screens tall, so the second screen starts at one scroll-container height.
 */
async function openFullHistory(page: Page) {
  await open(page, '/history')
  await expect(page.getByTestId('history-scroll-hint')).toBeVisible()
  await page.getByTestId('history-scroll-hint').click()
  const full = page.getByTestId('history-full')
  await expect(full).toBeInViewport({ ratio: 0.9 })
  await expect
    .poll(() => page.getByTestId('history-scroll').evaluate((el) => el.scrollTop))
    .toBeGreaterThan(100)
  return full
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

test('task cards change background on hover without moving', async ({ page }) => {
  await open(page, '/tasks')
  const card = page.getByTestId('mode-first_launch')
  const before = await card.boundingBox()
  if (!before) throw new Error('task card has no box')
  const beforeColor = await card.evaluate((el) => getComputedStyle(el).backgroundColor)
  await card.hover()
  await expect.poll(() => card.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(beforeColor)
  const after = await card.boundingBox()
  expect(after).toEqual(before)
})

test('drill arm goes through confirm and switches to the live view', async ({ page }) => {
  await open(page, '/tasks', 'empty')
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('如 JX040229').fill('JX040229')
  await dialog.getByPlaceholder('如 5000').fill('0.01')
  await dialog.getByRole('switch').first().click() // 演练
  await dialog.getByRole('switch').nth(1).click() // 立即排练
  await dialog.getByRole('button', { name: '下一步' }).click()
  await expect(dialog.getByTestId('confirm-price')).toContainText('约三分钟后')
  await expect(dialog.getByTestId('confirm-price')).toContainText('0.01')
  await dialog.getByRole('button', { name: '开始演练' }).click()
  await expect(page.getByTestId('live')).toBeVisible()
  await expect(page.getByTestId('countdown')).toHaveAttribute('aria-label', /^0[23]:\d\d$/)
})

test('real arm needs the amount checkbox', async ({ page }) => {
  await open(page, '/tasks', 'empty')
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('如 JX040229').fill('JX040229')
  await dialog.getByPlaceholder('如 5000').fill('100')
  await dialog.getByRole('button', { name: '下一步' }).click()
  const confirm = dialog.getByRole('button', { name: '确认真实布防' })
  await expect(dialog.getByTestId('confirm-price')).toContainText('100.00')
  await expect(confirm).toBeDisabled()
  await dialog.getByTestId('confirm-check').check()
  await expect(confirm).toBeEnabled()
  await dialog.getByTestId('confirm-check').uncheck()
  await expect(confirm).toBeDisabled()
})

test('real arm accepts an amount above 60000', async ({ page }) => {
  await open(page, '/tasks', 'empty')
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('如 JX040229').fill('JX040229')
  await dialog.getByPlaceholder('如 5000').fill('60000')
  await dialog.getByRole('button', { name: '下一步' }).click()
  // No upper limit any more: the amount goes straight to the real-payment confirm page.
  await expect(dialog.getByTestId('confirm-price')).toContainText('60,000.00')
  await expect(dialog.getByTestId('confirm-check')).toBeVisible()
})

/** Local YYYY-MM-DD offset from today; the fixtures use the same idea for expired demos. */
function localDate(daysFromToday: number) {
  const date = new Date(Date.now() + daysFromToday * 86_400_000)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

test('favourite code shows its historical success count', async ({ page }) => {
  await open(page, '/favorites', 'idle')
  // The demo history has one real successful submission on this favourite's code
  // (the saved test item), and none for the others.
  const tag = page.getByTestId('success-tag-133045A')
  await expect(tag).toBeVisible()
  await expect(tag).toHaveText('1 单')
  await expect(page.getByTestId('favorite-code-133045A')).toBeVisible()
  await expect(page.getByTestId('success-tag-JX040229')).toHaveCount(0)
  await expect(page.getByTestId('success-tag-GS110021')).toHaveCount(0)
  // Drills never count: GS110021 only has a 演练 record.
  await expect(page.getByTestId('test-tag-133045A')).toBeVisible()
})

test('favourites test item fills drills', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('favorite-settings-AB1234').click()
  const config = page.getByTestId('favorite-settings-dialog')
  await config.getByTestId('test-item-check').check()
  await config.getByTestId('test-amount-input').fill('0.02')
  await config.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('test-tag-AB1234')).toHaveText('测试 ¥0.02')

  await page.getByRole('link', { name: '演练' }).click()
  await expect(page.getByTestId('favorite-AB1234')).toContainText('测试 ¥0.02')
  await expect(page.getByPlaceholder('如 JX040229')).toHaveValue('AB1234')
  await expect(page.getByPlaceholder('0.01').first()).toHaveValue('0.02')
  await page.getByRole('button', { name: '打开演练布防' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByPlaceholder('如 JX040229')).toHaveValue('AB1234')
  await expect(dialog.getByPlaceholder('如 5000')).toHaveValue('0.02')
})

test('test favourite chip fills code and amount in the arm form', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('favorite-settings-AB1234').click()
  const config = page.getByTestId('favorite-settings-dialog')
  await config.getByTestId('test-item-check').check()
  await config.getByTestId('test-amount-input').fill('0.02')
  await config.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('test-tag-AB1234')).toBeVisible()

  await page.getByRole('link', { name: '任务' }).click()
  await page.getByTestId('mode-first_launch').getByRole('button', { name: '新建布防' }).click()
  const dialog = page.getByRole('dialog')
  const chip = dialog.getByTestId('favorite-AB1234')
  await expect(chip).toContainText('测试 ¥0.02')
  await chip.click()
  await expect(dialog.getByPlaceholder('如 JX040229')).toHaveValue('AB1234')
  await expect(dialog.getByPlaceholder('如 5000')).toHaveValue('0.02')
})

test('favourites test item can be cleared in the settings dialog', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('favorite-settings-AB1234').click()
  const config = page.getByTestId('favorite-settings-dialog')
  await config.getByTestId('test-item-check').check()
  await config.getByTestId('test-amount-input').fill('0.02')
  await config.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('test-tag-AB1234')).toBeVisible()
  await expect(config).toBeHidden()

  await page.getByTestId('favorite-settings-AB1234').click()
  const reopened = page.getByTestId('favorite-settings-dialog')
  await reopened.getByTestId('test-item-check').uncheck()
  await reopened.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('test-tag-AB1234')).toBeHidden()
})

test('favourite row actions fit the minimum window', async ({ page }) => {
  await page.setViewportSize({ width: 940, height: 680 })
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  const remove = page.getByRole('button', { name: '删除' })
  await expect(remove).toBeVisible()
  const box = await remove.boundingBox()
  if (!box) throw new Error('delete button has no box')
  expect(box.x + box.width).toBeLessThanOrEqual(940)
  await expect(page.getByTestId('favorite-settings-AB1234')).toBeVisible()
  await expect(page.getByLabel('AB1234 标题')).toBeVisible()
  await expect(page.getByTestId('quota-times-AB1234')).toContainText('未设置额度时间')

  // The settings editor with one row also stays inside the minimum window.
  await page.getByTestId('favorite-settings-AB1234').click()
  const dialog = page.getByTestId('favorite-settings-dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByTestId('quota-add').click()
  const saveButton = dialog.getByTestId('save-favorite-settings')
  await expect(saveButton).toBeVisible()
  const saveBox = await saveButton.boundingBox()
  if (!saveBox) throw new Error('save button has no box')
  expect(saveBox.x + saveBox.width).toBeLessThanOrEqual(940)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
})

test('favourite settings show kinds, expiry, quota amounts and notes', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('favorite-settings-AB1234').click()
  const dialog = page.getByTestId('favorite-settings-dialog')
  await dialog.getByTestId('quota-add').click()
  await dialog.getByTestId('quota-add').click()
  await dialog.getByTestId('quota-add').click()

  // 1) An already expired 首发 with 5000 万.
  await dialog.getByTestId('quota-kind-0').selectOption('issue')
  await dialog.getByTestId('quota-date-0').fill(localDate(-3))
  await dialog.getByTestId('quota-time-0').fill('09:00')
  await dialog.getByTestId('quota-amount-unset-0').uncheck()
  await dialog.getByTestId('quota-amount-0').fill('5000')
  await dialog.getByTestId('quota-note-0').fill('首发 5000 万')

  // 2) 捡漏 on 周一～周六 at 00:15 with an open amount.
  await dialog.getByTestId('quota-kind-1').selectOption('bargain')
  for (const day of [2, 3, 4, 5, 6]) await dialog.getByTestId(`quota-weekday-1-${day}`).click()
  await dialog.getByTestId('quota-time-1').fill('00:15')

  // 3) 常规 keeps the defaults (周一 09:00) and records 100 万.
  await dialog.getByTestId('quota-amount-unset-2').uncheck()
  await dialog.getByTestId('quota-amount-2').fill('100')

  await dialog.getByTestId('save-favorite-settings').click()
  await expect(dialog).toBeHidden()

  const list = page.getByTestId('quota-times-AB1234')
  await expect(list.locator('li')).toHaveCount(3)
  await expect(list).toContainText('首发')
  await expect(list).toContainText('已过期')
  await expect(list).toContainText('捡漏')
  await expect(list).toContainText('常规')
  await expect(list).toContainText('5000 万')
  await expect(list).toContainText('不定额度')
  await expect(list).toContainText('周一～周六 00:15')
  await expect(list).toContainText('100 万')
  await expect(list).toContainText('首发 5000 万')
})

test('setting another favourite moves the test item', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  for (const [code, title] of [
    ['AB1234', '测试产品'],
    ['CD5678', '第二产品'],
  ]) {
    await page.getByPlaceholder('如 JX040229').fill(code)
    await page.getByPlaceholder('如 招睿丰和 30 天').fill(title)
    await page.getByRole('button', { name: '添加', exact: true }).click()
  }

  await page.getByTestId('favorite-settings-AB1234').click()
  let dialog = page.getByTestId('favorite-settings-dialog')
  await dialog.getByTestId('test-item-check').check()
  await dialog.getByTestId('test-amount-input').fill('0.02')
  await dialog.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('test-tag-AB1234')).toHaveText('测试 ¥0.02')

  await page.getByTestId('favorite-settings-CD5678').click()
  dialog = page.getByTestId('favorite-settings-dialog')
  await dialog.getByTestId('test-item-check').check()
  await expect(dialog).toContainText('当前测试项是 AB1234')
  await dialog.getByTestId('test-amount-input').fill('0.05')
  await dialog.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('test-tag-CD5678')).toHaveText('测试 ¥0.05')
  await expect(page.getByTestId('test-tag-AB1234')).toBeHidden()
})

test('invalid quota input disables saving settings', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('favorite-settings-AB1234').click()
  const dialog = page.getByTestId('favorite-settings-dialog')
  const save = dialog.getByTestId('save-favorite-settings')
  await expect(save).toBeEnabled()
  await dialog.getByTestId('quota-add').click()

  // 首发 without a date cannot be saved.
  await dialog.getByTestId('quota-kind-0').selectOption('issue')
  await expect(save).toBeDisabled()
  await expect(dialog).toContainText('请选择首发日期。')
  await dialog.getByTestId('quota-date-0').fill(localDate(-1))
  await expect(save).toBeEnabled()

  await dialog.getByTestId('quota-add').click()
  // A weekly entry needs at least one weekday.
  await dialog.getByTestId('quota-weekday-1-1').click()
  await expect(save).toBeDisabled()
  await expect(dialog).toContainText('请至少选择一个星期。')
  await dialog.getByTestId('quota-weekday-1-1').click()
  await expect(save).toBeEnabled()

  // 不定额度 off requires a positive amount with at most two decimals.
  await dialog.getByTestId('quota-amount-unset-1').uncheck()
  await expect(save).toBeDisabled()
  await expect(dialog).toContainText('请填写额度数量。')
  await dialog.getByTestId('quota-amount-1').fill('0.123')
  await expect(save).toBeDisabled()
  await dialog.getByTestId('quota-amount-1').fill('5000')
  await expect(save).toBeEnabled()
})

test('favourite settings remove and clear quota times', async ({ page }) => {
  await open(page, '/favorites', 'idle')
  const list = page.getByTestId('quota-times-JX040229')
  await expect(list.getByRole('listitem')).toHaveCount(3)

  await page.getByTestId('favorite-settings-JX040229').click()
  let dialog = page.getByTestId('favorite-settings-dialog')
  await dialog.getByTestId('quota-remove-0').click()
  await dialog.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('favorite-settings-dialog')).toBeHidden()
  await expect(list.getByRole('listitem')).toHaveCount(2)

  await page.getByTestId('favorite-settings-JX040229').click()
  dialog = page.getByTestId('favorite-settings-dialog')
  await dialog.getByTestId('quota-remove-0').click()
  await dialog.getByTestId('quota-remove-0').click()
  await dialog.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('favorite-settings-dialog')).toBeHidden()
  await expect(list.getByRole('listitem')).toHaveCount(0)
  await expect(list).toContainText('未设置额度时间')
})

test('favourite row shows the recorded recent annualized yield', async ({ page }) => {
  await open(page, '/favorites', 'idle')
  const annualized = page.getByTestId('annualized-JX040229')
  await expect(annualized).toHaveText('近期年化 2.85%')
  await expect(annualized).toHaveAttribute('title', '近期年化 2.85%')
})

test('favourite recent annualized can be recorded and cleared in the settings dialog', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await expect(page.getByTestId('annualized-AB1234')).toBeHidden()

  await page.getByTestId('favorite-settings-AB1234').click()
  let dialog = page.getByTestId('favorite-settings-dialog')
  await expect(dialog.getByTestId('annualized-input')).toHaveValue('')
  await dialog.getByTestId('annualized-input').fill('3.1')
  await dialog.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('favorite-settings-dialog')).toBeHidden()
  await expect(page.getByTestId('annualized-AB1234')).toHaveText('近期年化 3.10%')

  await page.getByTestId('favorite-settings-AB1234').click()
  dialog = page.getByTestId('favorite-settings-dialog')
  await expect(dialog.getByTestId('annualized-input')).toHaveValue('3.10%')
  await dialog.getByTestId('annualized-input').fill('')
  await dialog.getByTestId('save-favorite-settings').click()
  await expect(page.getByTestId('favorite-settings-dialog')).toBeHidden()
  await expect(page.getByTestId('annualized-AB1234')).toBeHidden()
})

test('invalid favourite recent annualized disables saving', async ({ page }) => {
  await open(page, '/favorites', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByTestId('favorite-settings-AB1234').click()
  const dialog = page.getByTestId('favorite-settings-dialog')
  const save = dialog.getByTestId('save-favorite-settings')
  const input = dialog.getByTestId('annualized-input')

  for (const value of ['abc', '3.123', '2000']) {
    await input.fill(value)
    await expect(save).toBeDisabled()
    await expect(dialog).toContainText('近期年化须为 -100 到 1000 之间的数字，最多两位小数，可带尾部 %。')
  }

  await input.fill('-100')
  await expect(save).toBeEnabled()
  await input.fill('1000.00%')
  await expect(save).toBeEnabled()
  await input.fill('')
  await expect(save).toBeEnabled()
})

test('favourite quota entries align with the title input', async ({ page }) => {
  await open(page, '/favorites', 'idle')
  const input = page.getByLabel('JX040229 标题')
  const entry = page.getByTestId('quota-entry-JX040229-0')
  await expect(entry).toBeVisible()
  const inputBox = await input.boundingBox()
  const entryBox = await entry.boundingBox()
  if (!inputBox || !entryBox) throw new Error('missing alignment boxes')
  expect(Math.abs(entryBox.x - inputBox.x)).toBeLessThanOrEqual(1)

  // A favourite without quota times starts at the same left edge too.
  await page.getByPlaceholder('如 JX040229').fill('AB1234')
  await page.getByPlaceholder('如 招睿丰和 30 天').fill('测试产品')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  const empty = page.getByTestId('quota-times-AB1234')
  await expect(empty).toContainText('未设置额度时间')
  const emptyInput = await page.getByLabel('AB1234 标题').boundingBox()
  const emptyBox = await empty.boundingBox()
  if (!emptyInput || !emptyBox) throw new Error('missing empty-state boxes')
  expect(Math.abs(emptyBox.x - emptyInput.x)).toBeLessThanOrEqual(1)
})

test('real single buy needs the amount checkbox', async ({ page }) => {
  await open(page, '/drill', 'empty')
  await page.getByPlaceholder('如 JX040229').fill('JX040229')
  await page.getByPlaceholder('0.01').first().fill('0.02')
  await page.getByRole('switch').first().click()
  await page.getByRole('button', { name: '直接购买…' }).click()
  const dialog = page.getByRole('dialog', { name: '确认真实单笔购买' })
  await expect(dialog.getByTestId('confirm-buy-price')).toContainText('0.02')
  const confirm = dialog.getByRole('button', { name: '确认实际付款' })
  await expect(confirm).toBeDisabled()
  await dialog.getByTestId('confirm-buy-check').check()
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
  await page.getByRole('dialog').getByTestId('favorite-AB1234').click()
  await expect(page.getByRole('dialog').getByPlaceholder('如 JX040229')).toHaveValue('AB1234')
})

test('history opens on a two-screen recent overview', async ({ page }) => {
  // The minimum window height is the tight case: both screens must still fit exactly.
  await page.setViewportSize({ width: 940, height: 680 })
  await open(page, '/history')
  const overview = page.getByTestId('history-overview')
  await expect(overview).toBeVisible()

  // 近期布防 mixes the latest real successes and failures: 8 rich cards in total.
  const recent = overview.getByTestId('recent-list')
  await expect(recent.getByRole('listitem')).toHaveCount(8)
  await expect(recent).toContainText('135002A')
  await expect(recent).toContainText('120084A')
  await expect(recent).toContainText('购买失败：额度不足')
  await expect(recent).toContainText('成功')
  await expect(recent).toContainText('失败')
  await expect(overview).toContainText('成功 5 · 失败 5')

  // Drills and the saved test item's product code stay off the first screen.
  await expect(recent).not.toContainText('133045A')
  await expect(recent).not.toContainText('GS110021')

  // Exactly two screens tall, no page scrollbar and no inner scrollbars on screen 1.
  const scroller = page.getByTestId('history-scroll')
  const metrics = await scroller.evaluate((el) => ({
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
    scrollbarWidth: getComputedStyle(el).scrollbarWidth,
  }))
  expect(metrics.clientHeight).toBeGreaterThan(300)
  expect(Math.abs(metrics.scrollHeight - 2 * metrics.clientHeight)).toBeLessThanOrEqual(2)
  expect(metrics.scrollbarWidth).toBe('none')
  expect(await scrollbarsIn(overview)).toEqual([])

  // The bottom hint stays on the first screen and jumps to the complete history.
  await expect(page.getByTestId('history-scroll-hint')).toBeInViewport()
  await page.getByTestId('history-scroll-hint').click()
  const full = page.getByTestId('history-full')
  await expect(full).toBeInViewport({ ratio: 0.9 })
  await expect(full.getByTestId('history-list').getByRole('listitem')).toHaveCount(14)
})

test('history flips a whole screen only after the wheel threshold', async ({ page }) => {
  await open(page, '/history')
  const scroller = page.getByTestId('history-scroll')
  const height = await scroller.evaluate((el) => el.clientHeight)
  expect(height).toBeGreaterThan(300)

  // Hover a blank spot on the first screen. A gesture below the 100px threshold
  // must not move the page at all; it never follows the scroll.
  await page.mouse.move(700, 200)
  await page.mouse.wheel(0, 60)
  await page.waitForTimeout(350)
  expect(await scroller.evaluate((el) => el.scrollTop)).toBe(0)

  // One gesture above the threshold flips exactly one screen.
  await page.mouse.wheel(0, 150)
  await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBe(height)

  // At the last screen there is nothing below it.
  const filter = await page.getByTestId('filter-all').boundingBox()
  if (!filter) throw new Error('filter card has no box')
  await page.mouse.move(filter.x + 20, filter.y + 20)
  await page.mouse.wheel(0, 400)
  await page.waitForTimeout(350)
  expect(await scroller.evaluate((el) => el.scrollTop)).toBe(height)

  // A full gesture up flips back to the first screen.
  await page.mouse.wheel(0, -150)
  await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBe(0)
})

test('history metric cards filter the complete list', async ({ page }) => {
  const full = await openFullHistory(page)
  const list = full.getByTestId('history-list')
  const rows = list.getByRole('listitem')

  await full.getByTestId('filter-failed').click()
  await expect(full.getByTestId('filter-failed')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows).toHaveCount(5)
  await expect(list).not.toContainText('135002A')
  await expect(list).toContainText('JX040229')
  await expect(full).toContainText('5 / 14 条')

  // Clicking the active card again clears the filter.
  await full.getByTestId('filter-failed').click()
  await expect(full.getByTestId('filter-failed')).toHaveAttribute('aria-pressed', 'false')
  await expect(rows).toHaveCount(14)

  // The five cards partition the records: 6 success + 5 failed + 1 cancelled + 2 drills.
  for (const [kind, count] of [
    ['success', 6],
    ['cancelled', 1],
    ['dry_run', 2],
  ] as const) {
    await full.getByTestId(`filter-${kind}`).click()
    await expect(rows).toHaveCount(count)
    await full.getByTestId(`filter-${kind}`).click()
  }
  await full.getByTestId('filter-success').click()
  // The complete list keeps the test-code record the overview filtered out.
  await expect(list).toContainText('133045A')
  await full.getByTestId('filter-success').click()
  await full.getByTestId('filter-dry_run').click()
  await expect(list).toContainText('演练')
  await full.getByTestId('filter-all').click()
  await expect(rows).toHaveCount(14)
})

test('history recent card opens that record in the complete history', async ({ page }) => {
  await open(page, '/history')
  await page
    .getByTestId('recent-list')
    .getByRole('button', { name: /135002A/ })
    .click()
  const detail = page.getByTestId('history-detail')
  await expect(detail).toContainText('135002A')
  await expect(detail).toContainText('提交成功')
  await expect(page.getByTestId('history-full')).toBeInViewport({ ratio: 0.9 })
})

test('history lists records and shows details', async ({ page }) => {
  const full = await openFullHistory(page)
  await full.getByRole('button', { name: /JX040229/ }).click()
  await expect(full.getByText('窗口内无额度')).toBeVisible()
  await expect(full.getByText('模拟器重启后恢复', { exact: false })).toBeVisible()
  await expect(full.getByTestId('history-detail')).toContainText('全程 14 分 16 秒')
})

test('inline log areas never scroll; the full log opens in a dialog', async ({ page }) => {
  await page.setViewportSize({ width: 940, height: 680 })

  // 状态 → 最近日志 card (screenshot 1): newest whole lines, no scrollbar.
  await open(page, '/status')
  const logCard = page.getByTestId('card-log')
  const recent = logCard.getByTestId('recent-log')
  await expect(recent).toBeVisible()
  await expect(recent).toContainText('查询门控已挂起')
  expect(await recent.locator('div').count()).toBe(6)
  expect(await scrollbarsIn(logCard)).toEqual([])

  // 历史 → 完整历史屏的值守日志 detail panel (screenshot 2): newest whole lines, no scrollbar.
  const full = await openFullHistory(page)
  await full.getByRole('button', { name: /JX040229/ }).click()
  const detail = page.getByTestId('history-detail')
  const historyLog = detail.getByTestId('history-log')
  await expect(historyLog).toBeVisible()
  await expect(historyLog).toContainText('查询门控已挂起')
  expect(await historyLog.locator('div').count()).toBeGreaterThan(1)
  // The log preview and the detail panel itself never scroll; the record list may.
  expect(await scrollbarsIn(historyLog)).toEqual([])
  expect(await detail.evaluate((el) => getComputedStyle(el).overflowY)).toBe('hidden')

  // Full log is still reachable through the dialog. The first cold WebKit run
  // can take several seconds to mount the Radix portal under parallel load;
  // wait for visibility explicitly instead of racing the default 5 s timeout.
  await detail.getByRole('button', { name: '查看全部' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible({ timeout: 10_000 })
  await expect(dialog).toContainText('全局 watch.log', { timeout: 10_000 })
})

test('drill buy shows command output', async ({ page }) => {
  await open(page, '/drill')
  await page.getByPlaceholder('如 JX040229').first().fill('JX040229')
  await page.getByRole('button', { name: '单笔购买演练' }).click()
  await expect(page.getByRole('dialog', { name: '命令输出' })).toContainText('输完密码，未点确定，演练结束')
})

test('settings other tab edits plan scheduler values', async ({ page }) => {
  await open(page, '/settings')
  await page.getByRole('radio', { name: '其他' }).click()
  await expect(page.getByTestId('other-settings')).toBeVisible()
  // Plan-mode health values live next to the monitor fields, with the same defaults as Python.
  await expect(page.getByLabel('健康检查最长等待')).toHaveValue('15')
  await expect(page.getByLabel('运行期健康检查间隔')).toHaveValue('300')
  const poll = page.getByLabel('轮询间隔')
  await poll.fill('3')
  await page.getByTestId('other-save').click()
  await expect(page.getByText('已保存，之后的新计划使用这套值')).toBeVisible()
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
