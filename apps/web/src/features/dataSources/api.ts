import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'
import type { Catalog, CatalogSnapshot, DataSource, DataSourceCreateInput, DataSourceCreateResult, DataSourcePage, ScanJob } from '../../lib/api/types'

export const dataSourceKeys = {
  all: (workspaceId: string) => ['workspaces', workspaceId, 'data-sources'] as const,
  detail: (workspaceId: string, dataSourceId: string) => ['workspaces', workspaceId, 'data-sources', dataSourceId] as const,
  jobs: (workspaceId: string, dataSourceId: string) => ['workspaces', workspaceId, 'data-sources', dataSourceId, 'jobs'] as const,
  job: (workspaceId: string, jobId: string) => ['workspaces', workspaceId, 'scan-jobs', jobId] as const,
  snapshots: (workspaceId: string, dataSourceId: string) => ['workspaces', workspaceId, 'data-sources', dataSourceId, 'snapshots'] as const,
  catalog: (workspaceId: string, dataSourceId: string, snapshotId: string) => ['workspaces', workspaceId, 'data-sources', dataSourceId, 'catalog', snapshotId] as const,
}

function idempotencyHeaders() {
  return { 'Idempotency-Key': crypto.randomUUID() }
}

export function useDataSources(workspaceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId ? dataSourceKeys.all(workspaceId) : ['data-sources', 'disabled'],
    queryFn: () => apiClient.request<DataSourcePage>(`/api/v1/workspaces/${workspaceId}/data-sources`),
    enabled: Boolean(workspaceId),
  })
}

export function useDataSourceDetail(workspaceId: string | undefined, dataSourceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId && dataSourceId ? dataSourceKeys.detail(workspaceId, dataSourceId) : ['data-source', 'disabled'],
    queryFn: () => apiClient.request<DataSource>(`/api/v1/workspaces/${workspaceId}/data-sources/${dataSourceId}`),
    enabled: Boolean(workspaceId && dataSourceId),
  })
}

export function useDataSourceJobs(workspaceId: string | undefined, dataSourceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId && dataSourceId ? dataSourceKeys.jobs(workspaceId, dataSourceId) : ['data-source-jobs', 'disabled'],
    queryFn: () => apiClient.request<ScanJob[]>(`/api/v1/workspaces/${workspaceId}/data-sources/${dataSourceId}/jobs`),
    enabled: Boolean(workspaceId && dataSourceId),
    refetchInterval: (query) => query.state.data?.some((job) => job.status === 'queued' || job.status === 'running') ? 1_000 : false,
    refetchIntervalInBackground: false,
  })
}

export function useCatalogSnapshots(workspaceId: string | undefined, dataSourceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId && dataSourceId ? dataSourceKeys.snapshots(workspaceId, dataSourceId) : ['catalog-snapshots', 'disabled'],
    queryFn: () => apiClient.request<CatalogSnapshot[]>(`/api/v1/workspaces/${workspaceId}/data-sources/${dataSourceId}/snapshots`),
    enabled: Boolean(workspaceId && dataSourceId),
  })
}

export function useCatalog(workspaceId: string, dataSourceId: string, snapshotId: string | undefined) {
  return useQuery({
    queryKey: snapshotId ? dataSourceKeys.catalog(workspaceId, dataSourceId, snapshotId) : ['catalog', 'disabled'],
    queryFn: () => apiClient.request<Catalog>('/api/v1/workspaces/' + workspaceId + '/data-sources/' + dataSourceId + '/catalog?snapshot_id=' + encodeURIComponent(snapshotId ?? '')),
    enabled: Boolean(snapshotId),
  })
}
export function useCreateDataSource(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: DataSourceCreateInput) => {
      if (!workspaceId) throw new Error('没有可用的工作空间。')
      return apiClient.request<DataSourceCreateResult>(`/api/v1/workspaces/${workspaceId}/data-sources`, {
        method: 'POST', body: JSON.stringify(input),
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
      return apiClient.request<ScanJob>(`/api/v1/workspaces/${workspaceId}/data-sources/${dataSourceId}/test`, {
        method: 'POST', headers: idempotencyHeaders(),
      })
    },
  })
}

export function useMetadataScan(workspaceId: string | undefined, dataSourceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (schemas: string[]) => {
      if (!workspaceId || !dataSourceId) throw new Error('数据源上下文不完整。')
      return apiClient.request<ScanJob>(`/api/v1/workspaces/${workspaceId}/data-sources/${dataSourceId}/scans`, {
        method: 'POST', headers: idempotencyHeaders(), body: JSON.stringify({ schemas }),
      })
    },
    onSuccess: async () => {
      if (workspaceId && dataSourceId) await queryClient.invalidateQueries({ queryKey: dataSourceKeys.jobs(workspaceId, dataSourceId) })
    },
  })
}

export function useCancelScanJob(workspaceId: string | undefined, dataSourceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => {
      if (!workspaceId) throw new Error('没有可用的工作空间。')
      return apiClient.request<ScanJob>(`/api/v1/workspaces/${workspaceId}/scan-jobs/${jobId}/cancel`, { method: 'POST' })
    },
    onSuccess: async () => {
      if (workspaceId && dataSourceId) await queryClient.invalidateQueries({ queryKey: dataSourceKeys.jobs(workspaceId, dataSourceId) })
    },
  })
}

export function useRetryScanJob(workspaceId: string | undefined, dataSourceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => {
      if (!workspaceId) throw new Error('没有可用的工作空间。')
      return apiClient.request<ScanJob>(`/api/v1/workspaces/${workspaceId}/scan-jobs/${jobId}/retry`, {
        method: 'POST', headers: idempotencyHeaders(),
      })
    },
    onSuccess: async () => {
      if (workspaceId && dataSourceId) await queryClient.invalidateQueries({ queryKey: dataSourceKeys.jobs(workspaceId, dataSourceId) })
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
