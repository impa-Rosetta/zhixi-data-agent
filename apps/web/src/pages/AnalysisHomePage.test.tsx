import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'

import type { AnalysisRunView } from '../features/analysisRuns/types'
import { AnalysisHomePage } from './AnalysisHomePage'

const mocks = vi.hoisted(() => ({
  role: 'analyst',
  view: undefined as AnalysisRunView | undefined,
  create: vi.fn(),
  message: vi.fn(),
  confirmation: vi.fn(),
  cancel: vi.fn(),
  retry: vi.fn(),
}))

vi.mock('../features/auth/context', () => ({
  useAuth: () => ({
    user: { display_name: '分析员' },
    workspace: { id: 'workspace-1', name: '质量空间', role: mocks.role },
  }),
}))

vi.mock('../features/analysisRuns/api', () => ({
  useAnalysisRuns: () => ({
    data: {
      items: mocks.view
        ? [{
          id: mocks.view.run.id,
          status: mocks.view.run.status,
          current_node: mocks.view.run.current_node,
          goal: '分析不良率',
          error_code: mocks.view.run.error_code,
          model_calls: 1,
          tool_calls: 0,
          total_tokens: 30,
          created_at: mocks.view.run.created_at,
          updated_at: mocks.view.run.updated_at,
          finished_at: mocks.view.run.finished_at,
        }]
        : [],
      total: mocks.view ? 1 : 0,
      limit: 30,
      offset: 0,
    },
    isLoading: false,
    isError: false,
  }),
  useAnalysisRunCommands: () => ({
    create: { mutateAsync: mocks.create, isPending: false },
    message: { mutateAsync: mocks.message, isPending: false },
    confirmation: { mutateAsync: mocks.confirmation, isPending: false },
    cancel: { mutateAsync: mocks.cancel, isPending: false },
    retry: { mutateAsync: mocks.retry, isPending: false },
  }),
}))

vi.mock('../features/analysisRuns/useRealtimeAnalysisRun', () => ({
  useRealtimeAnalysisRun: () => ({
    data: mocks.view,
    events: [],
    connection: mocks.view ? 'live' : 'idle',
    streamError: null,
    isLoading: false,
    isError: false,
  }),
}))

function runView(status: AnalysisRunView['run']['status']): AnalysisRunView {
  return {
    run: {
      id: 'run-1',
      workspace_id: 'workspace-1',
      status,
      current_node: 'execute',
      context: {
        goal: '分析不良率',
        ...(status === 'waiting_for_clarification' ? {
          clarification: {
            reason_code: 'metric_required',
            question: '你希望分析哪个指标？',
            missing_fields: ['metrics'],
            candidates: [],
            suggested_answers: ['分析不良率', '分析一次通过率'],
            resume_node: 'understand',
          },
        } : {}),
      },
      frozen_versions: { semantic_version_id: 'semantic-v1' },
      budget: { max_model_calls: 6, max_tool_calls: 12 },
      model_calls: 1,
      tool_calls: 0,
      total_tokens: 30,
      replan_count: 0,
      error_code: status === 'failed_retryable' ? 'model.not_configured' : null,
      version: 2,
      cancel_requested_at: null,
      started_at: '2026-09-09T00:00:00Z',
      created_at: '2026-09-09T00:00:00Z',
      updated_at: '2026-09-09T00:01:00Z',
      finished_at: null,
    },
    messages: [{
      id: 'message-1',
      role: 'user',
      content: '分析不良率',
      context_patch: {},
      created_at: '2026-09-09T00:00:00Z',
    }],
    plan: {
      id: 'plan-1',
      revision: 1,
      goal: '分析不良率',
      document: {},
      requires_confirmation: status === 'waiting_for_confirmation',
      confirmed_at: null,
      created_at: '2026-09-09T00:00:30Z',
    },
    steps: [{
      id: 'step-1',
      plan_id: 'plan-1',
      step_key: 'query',
      tool_name: 'query.metric',
      arguments: { metric: 'defect_rate' },
      dependencies: [],
      status: 'running',
      error_code: null,
      started_at: '2026-09-09T00:00:40Z',
      finished_at: null,
    }],
    tool_calls: [],
    artifacts: [],
    evidence: [],
    validations: [],
    last_event_sequence: 3,
  }
}

function renderPage(path = '/app') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/app" element={<AnalysisHomePage />} />
          <Route path="/app/analysis/:runId" element={<AnalysisHomePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mocks.role = 'analyst'
  mocks.view = undefined
  vi.clearAllMocks()
  mocks.create.mockResolvedValue({ id: 'run-new' })
})

test('creates a real analysis run from the empty workbench', async () => {
  renderPage()
  fireEvent.change(screen.getByLabelText('分析问题'), {
    target: { value: '本月哪条产线的不良率最高？' },
  })
  fireEvent.click(screen.getByRole('button', { name: '开始分析' }))

  await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
  expect(mocks.create).toHaveBeenCalledWith(
    expect.objectContaining({ message: '本月哪条产线的不良率最高？' }),
  )
})

test('shows a running plan and allows cancellation', async () => {
  mocks.view = runView('running')
  renderPage('/app/analysis/run-1')

  expect(screen.getByText('query.metric')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '取消任务' }))
  await waitFor(() => expect(mocks.cancel).toHaveBeenCalledWith('run-1'))
})

test('requires an explicit decision for a confirmation-gated plan', async () => {
  mocks.view = runView('waiting_for_confirmation')
  renderPage('/app/analysis/run-1')

  fireEvent.click(screen.getByRole('button', { name: '批准并执行' }))
  await waitFor(() =>
    expect(mocks.confirmation).toHaveBeenCalledWith({ runId: 'run-1', approved: true }),
  )
  fireEvent.click(screen.getByRole('button', { name: '拒绝计划' }))
  await waitFor(() =>
    expect(mocks.confirmation).toHaveBeenCalledWith({ runId: 'run-1', approved: false }),
  )
})

test('submits clarification and resumes the existing run', async () => {
  mocks.view = runView('waiting_for_clarification')
  renderPage('/app/analysis/run-1')

  fireEvent.change(screen.getByLabelText('补充说明'), {
    target: { value: '统计 2026 年 8 月的所有产线' },
  })
  fireEvent.click(screen.getByRole('button', { name: '提交并继续' }))
  await waitFor(() =>
    expect(mocks.message).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: 'run-1',
        message: '统计 2026 年 8 月的所有产线',
      }),
    ),
  )
})

test('shows an actionable clarification and lets a suggestion fill the response', () => {
  mocks.view = runView('waiting_for_clarification')
  renderPage('/app/analysis/run-1')

  expect(screen.getByText('你希望分析哪个指标？')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '分析不良率' }))
  expect(screen.getByLabelText('补充说明')).toHaveValue('分析不良率')
})

test('retries a recoverable failure from its checkpoint', async () => {
  mocks.view = runView('failed_retryable')
  renderPage('/app/analysis/run-1')

  fireEvent.click(screen.getByRole('button', { name: '从检查点重试' }))
  await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith('run-1'))
})

test('keeps auditors out of execution controls', () => {
  mocks.role = 'auditor'
  renderPage()
  expect(screen.getByText('审计员只能查看治理与审计信息，不能发起分析任务。')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '开始分析' })).not.toBeInTheDocument()
})
