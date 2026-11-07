import { expect, type Page, test } from '@playwright/test'

/** Opens the credentials tab, where the push card lives. */
async function openPush(page: Page, scenario: string) {
  await page.goto(`/?scenario=${scenario}#/settings`)
  await page.getByRole('radio', { name: '凭据' }).click()
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
