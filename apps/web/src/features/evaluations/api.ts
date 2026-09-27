import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'

export type EvaluationRun = {
  id: string
  workspace_id: string
  track: 'offline' | 'live'
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'
  suite_version: string
  suite_digest: string
  dataset_id: string
  semantic_version: string
  model_version: string
  tool_version: string
  prompt_version: string
  summary: Record<string, unknown>
  budget: { max_seconds?: number }
  calls_used: number
  tokens_used: number
  attempt_count: number
  error_code: string | null
  created_at: string
}

export type EvaluationCaseResult = {
  case_id: string
  category: string
  status: string
  attempt_count: number
  duration_ms: number
  assertion_results: Array<{ name: string; passed: boolean }>
  run_references: string[]
  error_code: string | null
}

type Page<T> = { items: T[]; total: number; limit: number; offset: number }
type SuiteMetadata = {
  items: Array<{
    suite_version: string
    suite_digest: string
    published: boolean
    case_count: number
    category_counts: Record<string, number>
    dataset_id: string
  }>
  offline_enabled: boolean
  live_enabled: boolean
  can_manage: boolean
}

const key = (workspaceId: string | undefined) => ['evaluations', workspaceId] as const
const path = (workspaceId: string | undefined) => `/api/v1/workspaces/${workspaceId}/evaluations`
const active = (status: string | undefined) => status === 'queued' || status === 'running'

export function useEvaluationSuites(workspaceId: string | undefined) {
  return useQuery({
    queryKey: [...key(workspaceId), 'suites'], enabled: Boolean(workspaceId),
    queryFn: () => apiClient.request<SuiteMetadata>(`${path(workspaceId)}/suites`),
  })
}

export function useEvaluationRuns(workspaceId: string | undefined, page = 0) {
  return useQuery({
    queryKey: [...key(workspaceId), 'runs', page], enabled: Boolean(workspaceId),
    queryFn: () => apiClient.request<Page<EvaluationRun>>(`${path(workspaceId)}?limit=30&offset=${page * 30}`),
    refetchInterval: (query) => query.state.data?.items.some((item) => active(item.status)) ? 2000 : false,
  })
}

export function useEvaluationDetail(workspaceId: string | undefined, runId: string | undefined) {
  return useQuery({
    queryKey: [...key(workspaceId), 'detail', runId], enabled: Boolean(workspaceId && runId),
    queryFn: () => apiClient.request<EvaluationRun>(`${path(workspaceId)}/${runId}`),
    refetchInterval: (query) => active(query.state.data?.status) ? 2000 : false,
  })
}

export function useEvaluationCases(
  workspaceId: string | undefined, runId: string | undefined, running: boolean,
  page = 0, category = 'all', status = 'all',
) {
  const filters = new URLSearchParams({ limit: '25', offset: String(page * 25) })
  if (category !== 'all') filters.set('category', category)
  if (status !== 'all') filters.set('status', status)
  return useQuery({
    queryKey: [...key(workspaceId), 'cases', runId, page, category, status], enabled: Boolean(workspaceId && runId),
    queryFn: () => apiClient.request<Page<EvaluationCaseResult>>(`${path(workspaceId)}/${runId}/cases?${filters.toString()}`),
    refetchInterval: running ? 2000 : false,
  })
}

export function useEvaluationCommands(workspaceId: string | undefined) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (command: { action: 'create'; version: string; idempotencyKey: string } | { action: 'cancel' | 'resume'; runId: string }) => {
      if (!workspaceId) throw new Error('请选择工作空间。')
      return command.action === 'create'
        ? apiClient.request<EvaluationRun>(path(workspaceId), {
            method: 'POST', headers: { 'Idempotency-Key': command.idempotencyKey },
            body: JSON.stringify({ suite_version: command.version, track: 'offline', max_seconds: 300 }),
          })
        : apiClient.request<null>(`${path(workspaceId)}/${command.runId}/${command.action}`, { method: 'POST' })
    },
    onSuccess: async () => { await client.invalidateQueries({ queryKey: key(workspaceId) }) },
  })
}
