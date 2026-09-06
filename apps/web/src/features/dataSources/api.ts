import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'
import type { DataSourceCreateInput, DataSourceCreateResult, DataSourcePage, ScanJob } from '../../lib/api/types'

export const dataSourceKeys = {
  all: (workspaceId: string) => ['workspaces', workspaceId, 'data-sources'] as const,
  job: (workspaceId: string, jobId: string) => ['workspaces', workspaceId, 'scan-jobs', jobId] as const,
}

export function useDataSources(workspaceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId ? dataSourceKeys.all(workspaceId) : ['data-sources', 'disabled'],
    queryFn: () => apiClient.request<DataSourcePage>(`/api/v1/workspaces/${workspaceId}/data-sources`),
    enabled: Boolean(workspaceId),
  })
}

export function useCreateDataSource(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: DataSourceCreateInput) => {
      if (!workspaceId) throw new Error('没有可用的工作空间。')
      return apiClient.request<DataSourceCreateResult>(`/api/v1/workspaces/${workspaceId}/data-sources`, {
        method: 'POST',
        body: JSON.stringify(input),
      })
    },
    onSuccess: async () => {
      if (workspaceId) await queryClient.invalidateQueries({ queryKey: dataSourceKeys.all(workspaceId) })
    },
  })
}

export function useTestConnection(workspaceId: string | undefined) {
  return useMutation({
    mutationFn: (dataSourceId: string) => {
      if (!workspaceId) throw new Error('没有可用的工作空间。')
      return apiClient.request<ScanJob>(
        `/api/v1/workspaces/${workspaceId}/data-sources/${dataSourceId}/test`,
        { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } },
      )
    },
  })
}

export function useScanJob(workspaceId: string | undefined, jobId: string | null) {
  return useQuery({
    queryKey: workspaceId && jobId ? dataSourceKeys.job(workspaceId, jobId) : ['scan-job', 'disabled'],
    queryFn: () => apiClient.request<ScanJob>(`/api/v1/workspaces/${workspaceId}/scan-jobs/${jobId}`),
    enabled: Boolean(workspaceId && jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 1_000 : false
    },
    refetchIntervalInBackground: false,
    meta: { purpose: 'connection-test-progress' },

  })
}
