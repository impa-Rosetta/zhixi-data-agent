import { expect, test } from '@playwright/test'

test('M7.7 previews and downloads an actual generated report', async ({ page }, testInfo) => {
  const conversationId = process.env.M77_CONVERSATION_ID
  const password = process.env.E2E_PASSWORD
  test.skip(!conversationId || !password, 'Isolated completed report fixture is required')
  await page.goto('/login')
  await page.getByLabel('邮箱').fill(process.env.E2E_EMAIL ?? 'owner@example.com')
  await page.getByLabel('密码').fill(password!)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/app\/?$/)
  await page.goto(`/app/conversations/${conversationId}`)
  const reports = page.getByRole('region', { name: '可信分析报告' })
  await expect(reports.getByText('已生成', { exact: true })).toBeVisible()
  await reports.getByRole('button', { name: '在线预览', exact: true }).click()
  const preview = page.frameLocator('iframe[title="第三季度质量分析报告预览"]')
  await expect(preview.getByRole('heading', { name: '第三季度质量分析报告' })).toBeVisible()
  await expect(preview.getByRole('columnheader', { name: '月份' })).toBeVisible()
  await expect(preview.getByRole('cell', { name: '2.4', exact: true })).toBeVisible()
  const downloaded = page.waitForEvent('download')
  await reports.getByRole('button', { name: 'PDF', exact: true }).click()
  const file = await downloaded
  expect(file.suggestedFilename()).toBe('第三季度质量分析报告.pdf')
  expect(await file.failure()).toBeNull()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m77-real-report.png'), fullPage: true })
  await page.reload()
  await expect(reports.getByText('已生成', { exact: true })).toBeVisible()
})
