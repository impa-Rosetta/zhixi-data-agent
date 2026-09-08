import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'
import type { AnalysisRunPage, AnalysisRunView } from './types'

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
