import { expect, test } from '@playwright/test'

const email = process.env.E2E_EMAIL ?? 'demo@zhixi.local'
const password = process.env.E2E_PASSWORD

test.beforeEach(async ({ page }) => {
  if (!password) throw new Error('E2E_PASSWORD is required and must not be committed')
  await page.goto('/login')
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/app(?:\/)?$/)
})

test('M3 semantic workbench creates and inspects the manufacturing template', async ({ page }, testInfo) => {
  await page.goto('/app/semantic')
  await expect(page.getByRole('heading', { name: '语义模型工作台' })).toBeVisible()
  await page.getByRole('button', { name: '从制造业模板创建' }).click()
  await expect(page.getByText('19', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('缺陷率', { exact: true })).toBeVisible()
  await expect(page.getByText('SUM(inspection.defect_quantity) ÷ SUM(inspection.inspected_quantity) × 100', { exact: true })).toBeVisible()
  await expect(page.getByLabel('数据源')).toBeVisible()
  await expect(page.getByRole('button', { name: '发布不可变版本' })).toBeEnabled()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m3-semantic-workbench.png'), fullPage: true })
})
