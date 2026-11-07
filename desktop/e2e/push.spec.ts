import { expect, type Page, test } from '@playwright/test'

/** Opens the dedicated push tab; all changes use the mock backend. */
async function openPush(page: Page, scenario: string) {
  await page.goto(`/?scenario=${scenario}#/settings`)
  await page.getByRole('radio', { name: '推送通知', exact: true }).click()
  return page.getByTestId('push-card')
}

test('push card shows saved config, saves, tests and clears', async ({ page }) => {
  const card = await openPush(page, 'idle')
  await expect(card.getByText('已配置')).toBeVisible()
  await expect(card.getByTestId('push-server')).toHaveValue('https://ntfy.example.com/')
  await expect(card.getByTestId('push-topic')).toHaveValue('cmb-demo')
  await expect(card.getByTestId('push-token')).toHaveAttribute('placeholder', '已保存，留空不修改')

  await card.getByTestId('push-topic').fill('cmb-new')
  await card.getByTestId('push-token').fill('pt_test_token')
  await card.getByTestId('push-save').click()
  await expect(card.getByText('已保存；之后的通知会发到这个频道。')).toBeVisible()
  await expect(card.getByTestId('push-token')).toHaveValue('')
  await expect(card.getByTestId('push-topic')).toHaveValue('cmb-new')

  await card.getByTestId('push-test').click()
  await expect(card.getByText('测试推送已发送，请在手机上查看。')).toBeVisible()

  await card.getByTestId('push-clear').click()
  await page.getByRole('alertdialog').getByRole('button', { name: '确认清除' }).click()
  await expect(card.getByText('已清除推送配置；通知只写日志。')).toBeVisible()
  await expect(card.getByText('未配置')).toBeVisible()
  await expect(card.getByTestId('push-save')).toBeDisabled()
})

test('notification tab is separate from credentials and persists detailed choices', async ({ page }) => {
  await page.goto('/?scenario=idle#/settings')
  await page.getByRole('radio', { name: '凭据', exact: true }).click()
  await expect(page.getByTestId('push-card')).toBeHidden()
  await expect(page.getByRole('heading', { name: '交易密码', exact: true })).toBeVisible()
  await page.getByRole('radio', { name: '推送通知', exact: true }).click()
  await expect(page.getByRole('heading', { name: '交易密码', exact: true })).toBeHidden()
  const preferences = page.getByTestId('push-preferences')
  await expect(preferences.getByRole('switch')).toHaveCount(24)
  const success = preferences.getByTestId('push-option-purchase_success').getByRole('switch')
  const unknown = preferences.getByTestId('push-option-purchase_unknown').getByRole('switch')
  await success.click()
  await expect(success).not.toBeChecked()
  await expect(unknown).toBeChecked()
  await preferences.getByTestId('push-preferences-save').click()
  await expect(preferences).toContainText('通知选项已保存。')
  await page.getByRole('radio', { name: '凭据', exact: true }).click()
  await page.getByRole('radio', { name: '推送通知', exact: true }).click()
  await expect(success).not.toBeChecked()
  await expect(unknown).toBeChecked()
  await preferences.getByRole('switch', { name: '开启手机推送', exact: true }).click()
  await expect(unknown).toBeDisabled()
  await preferences.getByTestId('push-preferences-save').click()
  await page.getByTestId('push-test').click()
  await expect(page.getByTestId('push-card')).toContainText('测试推送已发送，请在手机上查看。')
  await preferences.getByRole('switch', { name: '开启手机推送', exact: true }).click()
  await expect(success).not.toBeChecked()
  await expect(unknown).toBeChecked()
})

test('notification preferences can be configured before credentials exist', async ({ page }) => {
  await openPush(page, 'empty')
  const preferences = page.getByTestId('push-preferences')
  await preferences.getByTestId('push-option-plan_item_completed').getByRole('switch').click()
  await preferences.getByTestId('push-preferences-save').click()
  await expect(preferences).toContainText('通知选项已保存。')
})

test('first save needs a token and shows the server failure reason', async ({ page }) => {
  const card = await openPush(page, 'empty')
  await expect(card.getByText('未配置')).toBeVisible()
  await card.getByTestId('push-server').fill('https://fail.example.com/')
  await card.getByTestId('push-topic').fill('cmb-demo')
  await expect(card.getByTestId('push-save')).toBeDisabled()

  await card.getByTestId('push-token').fill('pt_test_token')
  await expect(card.getByTestId('push-save')).toBeEnabled()
  await card.getByTestId('push-save').click()
  await expect(card.getByText('已配置')).toBeVisible()

  await card.getByTestId('push-test').click()
  await expect(card.getByText('测试推送失败：HTTP 401。')).toBeVisible()
})
