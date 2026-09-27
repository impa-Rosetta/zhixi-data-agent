import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'

import { EvaluationsPage } from './EvaluationsPage'

const mocks = vi.hoisted(() => {
  const summary: Record<string, unknown> = {}
  const runItems: Array<{ id: string; suite_version: string; track: string; status: string; created_at: string }> = []
  const caseItems: Array<{ case_id: string; category: string; status: string; assertion_results: Array<{ name: string; passed: boolean }>; duration_ms: number; error_code: string | null }> = []
  const comparisonSummary: Record<string, unknown> = {}
  return {
  role: 'workspace_admin', manage: true, enabled: true,
  summary, command: vi.fn(), runItems, caseItems, runsTotal: 0, casesTotal: 0,
  runPage: vi.fn(), caseFilter: vi.fn(),
  comparisonSummary, comparisonDigest: 'a'.repeat(64),
  }
})
vi.mock('../features/auth/context', () => ({
  useAuth: () => ({ workspace: { id: 'fixture', role: mocks.role } }),
}))
vi.mock('../features/evaluations/api', () => ({
  useEvaluationSuites: () => ({ data: {
    can_manage: mocks.manage, offline_enabled: mocks.enabled, live_enabled: false,
    items: [{ suite_version: '0.1.2', suite_digest: 'a'.repeat(64), published: false,
      case_count: 9, dataset_id: 'synthetic-fixture', category_counts: { standard: 3 } }],
  } }),
  useEvaluationRuns: (_workspace: string, page: number) => {
    mocks.runPage(page)
    return { data: { items: mocks.runItems, total: mocks.runsTotal } }
  },
  useEvaluationDetail: (_workspace: string, id: string | undefined) => ({ data: id ? {
    id, status: 'completed', track: 'offline', model_version: 'offline-fixed-v1',
    suite_version: '0.1.2', dataset_id: 'synthetic-fixture', semantic_version: 'fixture-v1',
    suite_digest: id === 'run' ? 'a'.repeat(64) : mocks.comparisonDigest,
    summary: id === 'run' ? mocks.summary : mocks.comparisonSummary,
    calls_used: 0, tokens_used: 0, attempt_count: 1, error_code: null,
  } : undefined }),
  useEvaluationCases: (_workspace: string, _run: string, _running: boolean, page: number, category: string, status: string) => {
    mocks.caseFilter(page, category, status)
    return { data: { items: mocks.caseItems, total: mocks.casesTotal } }
  },
  useEvaluationCommands: () => ({ mutateAsync: mocks.command, isPending: false }),
}))

beforeEach(() => {
  mocks.role = 'workspace_admin'; mocks.manage = true; mocks.enabled = true
  mocks.summary = {}; mocks.command.mockReset()
  mocks.runsTotal = 1; mocks.casesTotal = 0
  mocks.runItems = [{ id: 'run', suite_version: '0.1.2', track: 'offline', status: 'completed', created_at: new Date().toISOString() }]
  mocks.caseItems = []; mocks.comparisonSummary = {}; mocks.comparisonDigest = 'a'.repeat(64)
  mocks.runPage.mockReset(); mocks.caseFilter.mockReset()
})
function show() { render(<MemoryRouter><EvaluationsPage /></MemoryRouter>) }

test('labels drafts and never fabricates missing metrics', () => {
  show()
  expect(screen.getByText(/未发布草案/)).toBeVisible()
  expect(screen.getByText(/不是 DeepSeek 实测准确率/)).toBeVisible()
  expect(screen.getAllByText('尚无结果')).toHaveLength(3)
  const start = screen.getByRole('button', { name: '运行离线评测' })
  expect(start).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox'))
  expect(start).toBeEnabled()
  expect(mocks.command).not.toHaveBeenCalled()
})

test('auditors are read-only and analysts receive minimal disclosure', () => {
  mocks.role = 'auditor'; mocks.manage = false
  show()
  expect(screen.queryByRole('button', { name: '运行离线评测' })).not.toBeInTheDocument()
})

test('unauthorized roles cannot see cached evaluation details', () => {
  mocks.role = 'analyst'
  show()
  expect(screen.getByRole('alert')).toHaveTextContent('没有评测访问权限')
  expect(screen.queryByText(/案例集摘要/)).not.toBeInTheDocument()
})

test('disabled environment cannot be enabled by checking the confirmation', () => {
  mocks.enabled = false
  show()
  fireEvent.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: '运行离线评测' })).toBeDisabled()
})

test('a single safety failure remains visible despite a high average', () => {
  mocks.summary = { evaluated_pass_rate: 0.99, coverage_rate: 1,
    all_case_pass_rate: 0.99, safety_failure_ids: ['dangerous-sql'] }
  show()
  expect(screen.getByRole('alert')).toHaveTextContent('存在安全案例失败')
  expect(screen.getAllByText('99.0%')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: '查看失败案例' }))
  expect(mocks.caseFilter).toHaveBeenLastCalledWith(0, 'security', 'failed')
})

test('server pages and filters are navigable rather than silently truncating results', () => {
  mocks.runsTotal = 31
  mocks.casesTotal = 26
  mocks.runItems = [{ id: 'listed', suite_version: '0.1.2', track: 'offline', status: 'completed', created_at: new Date().toISOString() }]
  mocks.caseItems = [{ case_id: 'first-case', category: 'standard', status: 'passed', assertion_results: [], duration_ms: 1, error_code: null }]
  show()
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(mocks.runPage).toHaveBeenLastCalledWith(1)
  fireEvent.click(screen.getByRole('button', { name: '下一页案例' }))
  expect(mocks.caseFilter).toHaveBeenLastCalledWith(1, 'all', 'all')
  fireEvent.change(screen.getByLabelText('场景类别'), { target: { value: 'security' } })
  expect(mocks.caseFilter).toHaveBeenLastCalledWith(0, 'security', 'all')
})

test('comparison shows a delta only for matching synthetic snapshots', () => {
  mocks.runItems.push({ id: 'other', suite_version: '0.1.2', track: 'offline', status: 'completed', created_at: new Date().toISOString() })
  mocks.summary = { coverage_rate: 0.9, evaluated_pass_rate: 0.9 }
  mocks.comparisonSummary = { coverage_rate: 0.8, evaluated_pass_rate: 0.8 }
  show()
  fireEvent.change(screen.getByLabelText('对照运行'), { target: { value: 'other' } })
  expect(screen.getByText(/覆盖率变化 10.0 个百分点/)).toBeVisible()
})

test('comparison refuses to compute a misleading delta for different suites', () => {
  mocks.runItems.push({ id: 'other', suite_version: '0.1.2', track: 'offline', status: 'completed', created_at: new Date().toISOString() })
  mocks.comparisonDigest = 'b'.repeat(64)
  show()
  fireEvent.change(screen.getByLabelText('对照运行'), { target: { value: 'other' } })
  expect(screen.getByText(/不计算通过率差值/)).toBeVisible()
  expect(screen.queryByText(/覆盖率变化/)).not.toBeInTheDocument()
})
