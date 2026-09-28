import { expect, test } from '@playwright/test'

test('M8 synthetic browser fixture renders comparable history without overflow', async ({ page }, testInfo) => {
  const workspaceId = 'trend-fixture-workspace'
  const base = {
    workspace_id: workspaceId, track: 'offline', status: 'completed',
    suite_version: '0.1.19', suite_digest: 'a'.repeat(64), dataset_id: 'synthetic-fixture',
    semantic_version: 'fixture-v1', model_version: 'offline-fixed-v1',
    tool_version: 'fixture-tools-v1', prompt_version: 'fixture-prompt-v1',
    budget: {}, calls_used: 0, tokens_used: 0, attempt_count: 1, error_code: null,
  }
  const runs = [
    { ...base, id: 'fixture-new', created_at: '2026-09-28T10:00:00Z',
      summary: { coverage_rate: 1, evaluated_pass_rate: 0.9, all_case_pass_rate: 0.9 } },
    { ...base, id: 'fixture-old', created_at: '2026-09-27T10:00:00Z',
      summary: { coverage_rate: 0.8, evaluated_pass_rate: 0.7, all_case_pass_rate: 0.56 } },
  ]
  await page.addInitScript(() => localStorage.setItem('zhixi.refresh-token', 'synthetic-browser-token'))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) {
      data = { access_token: 'synthetic-access', refresh_token: 'synthetic-browser-token', token_type: 'bearer' }
    } else if (path.endsWith('/auth/me')) {
      data = { id: 'fixture-user', email: 'fixture@example.invalid', display_name: '合成验收用户',
        workspaces: [{ id: workspaceId, name: '合成趋势验收', role: 'workspace_admin' }] }
    } else if (path.endsWith('/evaluations/suites')) {
      data = { can_manage: false, offline_enabled: false, live_enabled: false,
        items: [{ suite_version: base.suite_version, suite_digest: base.suite_digest,
          published: false, case_count: 2, dataset_id: base.dataset_id, category_counts: { standard: 2 } }] }
    } else if (path.endsWith('/evaluations')) {
      data = { items: runs, total: runs.length, limit: 30, offset: 0 }
    } else if (path.endsWith('/cases')) {
      data = { items: [], total: 0, limit: 25, offset: 0 }
    } else if (path.endsWith('/evaluations/fixture-new')) {
      data = runs[0]
    } else {
      await route.abort()
      return
    }
    await route.fulfill({ json: data })
  })
  await page.goto('/app/evaluations')
  const trend = page.getByRole('region', { name: '历史趋势' })
  await expect(trend.getByRole('img')).toBeVisible()
  await expect(trend.locator('polyline')).toHaveCount(2)
  await expect(trend.getByRole('row', { name: /80\.0%.*70\.0%/ })).toBeVisible()
  await expect(trend.getByRole('row', { name: /100\.0%.*90\.0%/ })).toBeVisible()
  await expect(page.getByText(/结果不是 DeepSeek 实测准确率/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('m8-synthetic-history-trend.png'), fullPage: true })
})
