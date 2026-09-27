import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'

import { EvaluationsPage } from './EvaluationsPage'

const mocks = vi.hoisted(() => {
  const summary: Record<string, unknown> = {}
  return {
  role: 'workspace_admin', manage: true, enabled: true,
  summary, command: vi.fn(),
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
  useEvaluationRuns: () => ({ data: { items: [] } }),
  useEvaluationDetail: () => ({ data: {
    id: 'run', status: 'completed', track: 'offline', model_version: 'offline-fixed-v1',
    suite_digest: 'a'.repeat(64), summary: mocks.summary,
    calls_used: 0, tokens_used: 0, attempt_count: 1, error_code: null,
  } }),
  useEvaluationCases: () => ({ data: { items: [], total: 0 } }),
  useEvaluationCommands: () => ({ mutateAsync: mocks.command, isPending: false }),
}))

beforeEach(() => {
  mocks.role = 'workspace_admin'; mocks.manage = true; mocks.enabled = true
  mocks.summary = {}; mocks.command.mockReset()
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
})
