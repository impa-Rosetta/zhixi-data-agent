import { expect, test } from '@playwright/test'

const email = process.env.E2E_EMAIL ?? 'demo@zhixi.local'
const password = process.env.E2E_PASSWORD
const acceptanceRunId = process.env.M6_ACCEPTANCE_RUN_ID

test.beforeEach(async ({ page }) => {
  if (!password) throw new Error('E2E_PASSWORD is required and must not be committed')
  await page.goto('/login')
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/app(?:\/)?$/)
})

test('M6 creates and restores a governed analysis run', async ({ page }, testInfo) => {
  const question = `验收任务 ${testInfo.project.name}：分析本月各产线不良率`
  await expect(page.getByRole('heading', { name: '企业数据智能问析' })).toBeVisible()
  await page.getByLabel('分析问题').fill(question)
  await page.getByRole('button', { name: '开始分析' }).click()

  await expect(page).toHaveURL(/\/app\/analysis\/[0-9a-f-]+$/)
  await expect(page.getByRole('heading', { name: question })).toBeVisible()

  if (testInfo.project.name === 'mobile-chrome') {
    await page.getByRole('button', { name: '执行' }).click()
  }
  await expect(page.getByRole('heading', { name: '运行详情' })).toBeVisible()
  await expect(page.getByText(/当前节点：|任务已创建|执行节点变化/).first()).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m6-analysis-workbench.png'), fullPage: true })
})

test('M6 renders a completed trusted result and its evidence', async ({ page }, testInfo) => {
  test.skip(!acceptanceRunId, 'M6_ACCEPTANCE_RUN_ID is required for live result acceptance')
  await page.goto(`/app/analysis/${acceptanceRunId}`)

  await expect(page.locator('.analysis-status-chip')).toHaveText('已完成')
  await expect(page.getByRole('heading', { name: '查询结果' })).toBeVisible()
  await expect(page.getByText('可信结果', { exact: true })).toBeVisible()
  await expect(page.getByText('1 行', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '定位证据' })).toBeVisible()

  if (testInfo.project.name === 'mobile-chrome') {
    await page.getByRole('button', { name: '执行' }).click()
  }
  await expect(page.getByText('查询执行证据')).toBeVisible()
  await expect(page.getByText('证据完整性')).toBeVisible()
  await expect(page.getByText('通过 · 0 个发现')).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m6-trusted-result.png'), fullPage: true })
})
