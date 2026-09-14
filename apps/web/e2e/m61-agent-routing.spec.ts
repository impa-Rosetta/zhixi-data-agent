import { expect, test } from '@playwright/test'

const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD
const capabilityRunId = process.env.M61_CAPABILITY_RUN_ID
const catalogRunId = process.env.M61_CATALOG_RUN_ID

test.beforeEach(async ({ page }) => {
  if (!email || !password) throw new Error('E2E_EMAIL and E2E_PASSWORD are required')
  if (!capabilityRunId || !catalogRunId) throw new Error('M6.1 acceptance run IDs are required')
  await page.goto('/login')
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/app(?:\/)?$/)
})

test('M6.1 renders a governed capability answer', async ({ page }, testInfo) => {
  await page.goto('/app/analysis/' + capabilityRunId)

  await expect(page.locator('.analysis-status-chip')).toHaveText('已完成')
  await expect(page.getByRole('heading', { name: 'Agent 能力说明' })).toBeVisible()
  await expect(page.getByText('清单 v1.0.0')).toBeVisible()
  await expect(page.getByRole('heading', { name: '当前可用' })).toBeVisible()
  await openExecutionOnMobile(page, testInfo.project.name)
  await expect(page.getByText('产品能力清单')).toBeVisible()
  await expect(page.getByText('能力范围')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: testInfo.outputPath('m61-capability-answer.png'), fullPage: true })
})

test('M6.1 renders authorized catalog structure and evidence', async ({ page }, testInfo) => {
  await page.goto('/app/analysis/' + catalogRunId)

  await expect(page.locator('.analysis-status-chip')).toHaveText('已完成')
  await expect(page.getByRole('heading', { name: '数据目录结果' })).toBeVisible()
  const result = page.getByRole('region', { name: '数据目录结果' })
  await expect(result.getByText(/quality_inspections/).first()).toBeVisible()
  await expect(page.getByText(/不包含数据样例/)).toBeVisible()
  await expect(page.locator('.analysis-catalog-fields strong').first()).toBeVisible()
  await openExecutionOnMobile(page, testInfo.project.name)
  await expect(page.getByText('目录快照证据').first()).toBeVisible()
  await expect(page.getByText('授权范围').first()).toBeVisible()
  await expect(page.getByText('敏感输出').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: testInfo.outputPath('m61-catalog-result.png'), fullPage: true })
})

async function openExecutionOnMobile(page: import('@playwright/test').Page, project: string) {
  if (project === 'mobile-chrome') {
    await page.getByRole('button', { name: '执行' }).click()
  }
}

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}
