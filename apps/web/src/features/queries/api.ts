import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'

export type ValidatedQuery = { id: string; workspace_id: string; data_source_id: string; semantic_model_id: string | null; semantic_version_id: string | null; snapshot_id: string; dialect: 'postgres' | 'mysql'; trust: 'trusted' | 'exploratory'; sql: string; parameter_count: number; dependencies: string[]; digest: string; expires_at: string; created_at: string }
export type QueryExecution = { id: string; validated_query_id: string; status: 'succeeded' | 'failed' | 'cancelled'; columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean; trust: 'trusted' | 'exploratory'; evidence_digest: string | null; error_code: string | null; started_at: string; finished_at: string }
export type SemanticQueryInput = { semantic_model_id: string; metrics: string[]; dimensions: string[]; filters: never[]; time_grain: string | null; comparison: 'none' | 'previous_period'; sort: { field: string; direction: 'asc' | 'desc' }[]; limit: number }

const historyKey = (workspaceId: string) => ['workspaces', workspaceId, 'query-executions'] as const

export function useCompileSemanticQuery(workspaceId: string | undefined) {
  return useMutation({ mutationFn: (input: SemanticQueryInput) => apiClient.request<ValidatedQuery>(`/api/v1/workspaces/${workspaceId}/queries/compile`, { method: 'POST', body: JSON.stringify(input) }) })
}

export function useValidateExploratoryQuery(workspaceId: string | undefined) {
  return useMutation({ mutationFn: (input: { data_source_id: string; sql: string; limit: number }) => apiClient.request<ValidatedQuery>(`/api/v1/workspaces/${workspaceId}/queries/validate-exploratory`, { method: 'POST', body: JSON.stringify(input) }) })
}

export function useExecuteValidatedQuery(workspaceId: string | undefined) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiClient.request<QueryExecution>(`/api/v1/workspaces/${workspaceId}/queries/${id}/execute`, { method: 'POST' }),
    onSuccess: async () => { if (workspaceId) await client.invalidateQueries({ queryKey: historyKey(workspaceId) }) },
  })
}

export function useQueryHistory(workspaceId: string | undefined) {
  return useQuery({ queryKey: workspaceId ? historyKey(workspaceId) : ['query-executions', 'disabled'], queryFn: () => apiClient.request<QueryExecution[]>(`/api/v1/workspaces/${workspaceId}/queries/executions`), enabled: Boolean(workspaceId) })
}
