import { afterEach, expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import {
  appendAnalysisMessage,
  cancelAnalysisRun,
  confirmAnalysisRun,
  createAnalysisRun,
  getAnalysisRunView,
  listAnalysisRuns,
  retryAnalysisRun,
} from './api'

afterEach(() => vi.restoreAllMocks())

test('requests a bounded analysis run page for the active workspace', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue({
    items: [],
    total: 0,
    limit: 20,
    offset: 40,
  })

  await listAnalysisRuns('workspace-1', 20, 40)

  expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/analysis-runs?limit=20&offset=40',
  )
})

test('requests the complete run projection without client-side reconstruction', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue({
    run: { id: 'run-1' },
    messages: [],
    plan: null,
    steps: [],
    tool_calls: [],
    artifacts: [],
    evidence: [],
    validations: [],
    last_event_sequence: 0,
  })

  await getAnalysisRunView('workspace-1', 'run-1')

  expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/analysis-runs/run-1/view',
  )
})

test('sends idempotent create and clarification commands', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue({ id: 'run-1' })

  await createAnalysisRun('workspace-1', '分析不良率', 'create-key')
  await appendAnalysisMessage(
    'workspace-1',
    'run-1',
    '我指的是本月不良率',
    'message-key',
  )

  expect(request.mock.calls[0]).toEqual([
    '/api/v1/workspaces/workspace-1/analysis-runs',
    expect.objectContaining({
      method: 'POST',
      headers: { 'Idempotency-Key': 'create-key' },
      body: JSON.stringify({ message: '分析不良率' }),
    }),
  ])
  expect(request.mock.calls[1]).toEqual([
    '/api/v1/workspaces/workspace-1/analysis-runs/run-1/messages',
    expect.objectContaining({
      method: 'POST',
      headers: { 'Idempotency-Key': 'message-key' },
    }),
  ])
})

test('routes confirmation, cancellation and retry through server state transitions', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue({ id: 'run-1' })

  await confirmAnalysisRun('workspace-1', 'run-1', true)
  await cancelAnalysisRun('workspace-1', 'run-1')
  await retryAnalysisRun('workspace-1', 'run-1')

  expect(request.mock.calls.map(([path]) => path)).toEqual([
    '/api/v1/workspaces/workspace-1/analysis-runs/run-1/confirm',
    '/api/v1/workspaces/workspace-1/analysis-runs/run-1/cancel',
    '/api/v1/workspaces/workspace-1/analysis-runs/run-1/retry',
  ])
  expect(request.mock.calls[0]?.[1]).toMatchObject({
    method: 'POST',
    body: JSON.stringify({ approved: true }),
  })
})
