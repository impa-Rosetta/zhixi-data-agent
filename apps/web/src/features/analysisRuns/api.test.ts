import { afterEach, expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import { getAnalysisRunView, listAnalysisRuns } from './api'

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
