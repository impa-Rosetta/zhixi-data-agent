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

test('M2 governance console works for PostgreSQL and MySQL at this viewport', async ({ page }, testInfo) => {
  await page.goto('/app/data')
  await expect(page.getByRole('heading', { name: '产品前端验收 PostgreSQL' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '产品前端验收 MySQL' })).toBeVisible()

  const mysqlCard = page.getByRole('article').filter({ hasText: '产品前端验收 MySQL' })
  await mysqlCard.getByRole('link', { name: '查看详情' }).click()
  await expect(page.getByRole('heading', { name: '产品前端验收 MySQL' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '数据源生命周期' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '采样与刷新' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '目录结构' })).toBeVisible()
  await expect(page.getByText('production_orders', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: '编辑配置' }).click()
  await expect(page.getByLabel('新账号')).toHaveValue('')
  await expect(page.getByLabel('新密码')).toHaveValue('')
  await page.getByRole('button', { name: '关闭' }).click()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m2-governance.png'), fullPage: true })
})
