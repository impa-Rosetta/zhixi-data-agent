import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'

export type ReportStatus = 'queued' | 'generating' | 'succeeded' | 'failed' | 'expired'
export type ReportFormat = 'markdown' | 'html' | 'pdf'

export type AnalysisReport = {
  id: string
  conversation_id: string
  title: string
  status: ReportStatus
  error_code: string | null
  created_at: string
  spec: {
    sections: Array<{
      source: {
        turn_id: string
        evidence_ids: string[]
      }
    }>
  }
}

type ReportPage = {
  items: AnalysisReport[]
  total: number
  limit: number
  offset: number
}

const reportKey = (workspaceId: string, conversationId: string) =>
  ['workspaces', workspaceId, 'reports', conversationId] as const

export function useConversationReports(
  workspaceId: string | undefined,
  conversationId: string | undefined,
) {
  return useQuery({
    queryKey: workspaceId && conversationId
      ? reportKey(workspaceId, conversationId)
      : ['reports', 'disabled'],
    queryFn: () => apiClient.request<ReportPage>(
      `/api/v1/workspaces/${workspaceId}/reports?conversation_id=${conversationId}`,
    ),
    enabled: Boolean(workspaceId && conversationId),
    refetchInterval: (query) => query.state.data?.items.some(
      (item) => item.status === 'queued' || item.status === 'generating',
    ) ? 3000 : false,
  })
}

export function useCreateConversationReport(
  workspaceId: string | undefined,
  conversationId: string | undefined,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { title: string; turnIds: string[]; idempotencyKey: string }) => {
      if (!workspaceId || !conversationId) throw new Error('请先打开一个分析会话。')
      return apiClient.request<AnalysisReport>(`/api/v1/workspaces/${workspaceId}/reports`, {
        method: 'POST',
        headers: { 'Idempotency-Key': input.idempotencyKey },
        body: JSON.stringify({
          conversation_id: conversationId,
          turn_ids: input.turnIds,
          title: input.title,
          template_key: 'quality-analysis-v1',
        }),
      })
    },
    onSuccess: async () => {
      if (workspaceId && conversationId) {
        await queryClient.invalidateQueries({ queryKey: reportKey(workspaceId, conversationId) })
      }
    },
  })
}

export function useRetryConversationReport(
  workspaceId: string | undefined,
  conversationId: string | undefined,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (reportId: string) => {
      if (!workspaceId) throw new Error('请先打开报告所在的工作空间。')
      return apiClient.request<AnalysisReport>(
        `/api/v1/workspaces/${workspaceId}/reports/${reportId}/retry`,
        { method: 'POST' },
      )
    },
    onSuccess: async () => {
      if (workspaceId && conversationId) {
        await queryClient.invalidateQueries({ queryKey: reportKey(workspaceId, conversationId) })
      }
    },
  })
}

export function downloadReportFile(
  workspaceId: string,
  reportId: string,
  format: ReportFormat,
): Promise<Blob> {
  return apiClient.requestBlob(
    `/api/v1/workspaces/${workspaceId}/reports/${reportId}/files/${format}`,
  )
}

export async function previewReportHtml(
  workspaceId: string,
  reportId: string,
): Promise<string> {
  const content = await apiClient.requestBlob(
    `/api/v1/workspaces/${workspaceId}/reports/${reportId}/preview`,
  )
  return content.text()
}
