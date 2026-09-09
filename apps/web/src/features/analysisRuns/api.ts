import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'
import type { AnalysisRun, AnalysisRunPage, AnalysisRunView } from './types'

export const analysisRunKeys = {
  all: (workspaceId: string) => ['workspaces', workspaceId, 'analysis-runs'] as const,
  page: (workspaceId: string, limit: number, offset: number) =>
    [...analysisRunKeys.all(workspaceId), 'page', limit, offset] as const,
  view: (workspaceId: string, runId: string) =>
    [...analysisRunKeys.all(workspaceId), runId, 'view'] as const,
}

export function listAnalysisRuns(
  workspaceId: string,
  limit = 30,
  offset = 0,
): Promise<AnalysisRunPage> {
  return apiClient.request(
    `/api/v1/workspaces/${workspaceId}/analysis-runs?limit=${limit}&offset=${offset}`,
  )
}

export function getAnalysisRunView(
  workspaceId: string,
  runId: string,
): Promise<AnalysisRunView> {
  return apiClient.request(
    `/api/v1/workspaces/${workspaceId}/analysis-runs/${runId}/view`,
  )
}

export function createAnalysisRun(
  workspaceId: string,
  message: string,
  idempotencyKey: string,
): Promise<AnalysisRun> {
  return apiClient.request(`/api/v1/workspaces/${workspaceId}/analysis-runs`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ message }),
  })
}

export function appendAnalysisMessage(
  workspaceId: string,
  runId: string,
  message: string,
  idempotencyKey: string,
): Promise<AnalysisRun> {
  return apiClient.request(
    `/api/v1/workspaces/${workspaceId}/analysis-runs/${runId}/messages`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ message }),
    },
  )
}

export function confirmAnalysisRun(
  workspaceId: string,
  runId: string,
  approved: boolean,
): Promise<AnalysisRun> {
  return apiClient.request(
    `/api/v1/workspaces/${workspaceId}/analysis-runs/${runId}/confirm`,
    { method: 'POST', body: JSON.stringify({ approved }) },
  )
}

export function cancelAnalysisRun(
  workspaceId: string,
  runId: string,
): Promise<AnalysisRun> {
  return apiClient.request(
    `/api/v1/workspaces/${workspaceId}/analysis-runs/${runId}/cancel`,
    { method: 'POST' },
  )
}

export function retryAnalysisRun(
  workspaceId: string,
  runId: string,
): Promise<AnalysisRun> {
  return apiClient.request(
    `/api/v1/workspaces/${workspaceId}/analysis-runs/${runId}/retry`,
    { method: 'POST' },
  )
}

export function useAnalysisRuns(
  workspaceId: string | undefined,
  limit = 30,
  offset = 0,
) {
  return useQuery({
    queryKey: workspaceId
      ? analysisRunKeys.page(workspaceId, limit, offset)
      : ['analysis-runs', 'disabled'],
    queryFn: () => listAnalysisRuns(workspaceId!, limit, offset),
    enabled: Boolean(workspaceId),
  })
}

export function useAnalysisRunView(
  workspaceId: string | undefined,
  runId: string | undefined,
) {
  return useQuery({
    queryKey:
      workspaceId && runId
        ? analysisRunKeys.view(workspaceId, runId)
        : ['analysis-run-view', 'disabled'],
    queryFn: () => getAnalysisRunView(workspaceId!, runId!),
    enabled: Boolean(workspaceId && runId),
  })
}

export function useAnalysisRunCommands(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  const refresh = async (run: AnalysisRun): Promise<void> => {
    if (!workspaceId) return
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: analysisRunKeys.all(workspaceId) }),
      queryClient.invalidateQueries({
        queryKey: analysisRunKeys.view(workspaceId, run.id),
      }),
    ])
  }
  const create = useMutation({
    mutationFn: (input: { message: string; idempotencyKey: string }) =>
      createAnalysisRun(workspaceId!, input.message, input.idempotencyKey),
    onSuccess: refresh,
  })
  const message = useMutation({
    mutationFn: (input: { runId: string; message: string; idempotencyKey: string }) =>
      appendAnalysisMessage(
        workspaceId!,
        input.runId,
        input.message,
        input.idempotencyKey,
      ),
    onSuccess: refresh,
  })
  const confirmation = useMutation({
    mutationFn: (input: { runId: string; approved: boolean }) =>
      confirmAnalysisRun(workspaceId!, input.runId, input.approved),
    onSuccess: refresh,
  })
  const cancel = useMutation({
    mutationFn: (runId: string) => cancelAnalysisRun(workspaceId!, runId),
    onSuccess: refresh,
  })
  const retry = useMutation({
    mutationFn: (runId: string) => retryAnalysisRun(workspaceId!, runId),
    onSuccess: refresh,
  })
  return { create, message, confirmation, cancel, retry }
}
