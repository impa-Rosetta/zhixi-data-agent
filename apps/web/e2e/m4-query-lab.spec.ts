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

test('M4 validates and executes exploratory SQL only through a validation ID', async ({ page }, testInfo) => {
  await page.goto('/app/queries')
  await expect(page.getByRole('heading', { name: '可信查询实验室' })).toBeVisible()
  await page.getByRole('button', { name: '探索 SQL' }).click()
  await page.getByLabel('目标数据源').selectOption({ index: 1 })
  await page.getByLabel('只读 SQL').fill('SELECT * FROM factory_demo.order_quality_summary')
  await page.getByRole('button', { name: '生成并安全校验' }).click()
  await expect(page.getByText('探索', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('factory_demo.order_quality_summary')).toBeVisible()
  await page.getByRole('button', { name: '仅凭验证 ID 执行' }).click()
  await expect(page.getByRole('heading', { name: '查询结果' })).toBeVisible()
  await expect(page.getByText(/证据摘要：/)).toBeVisible()
  await expect(page.getByText('2 行结果').first()).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m4-query-lab.png'), fullPage: true })
})
