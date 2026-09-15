import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'
import type {
  AnalysisConversation,
  AnalysisConversationPage,
  AnalysisConversationView,
} from './types'

export const analysisConversationKeys = {
  all: (workspaceId: string) => ['workspaces', workspaceId, 'analysis-conversations'] as const,
  page: (workspaceId: string) => [...analysisConversationKeys.all(workspaceId), 'page'] as const,
  view: (workspaceId: string, conversationId: string) =>
    [...analysisConversationKeys.all(workspaceId), conversationId, 'view'] as const,
}

export function useAnalysisConversations(workspaceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId
      ? analysisConversationKeys.page(workspaceId)
      : ['analysis-conversations', 'disabled'],
    queryFn: () => apiClient.request<AnalysisConversationPage>(
      `/api/v1/workspaces/${workspaceId}/analysis-conversations`,
    ),
    enabled: Boolean(workspaceId),
  })
}

export function useAnalysisConversationView(
  workspaceId: string | undefined,
  conversationId: string | undefined,
) {
  return useQuery({
    queryKey: workspaceId && conversationId
      ? analysisConversationKeys.view(workspaceId, conversationId)
      : ['analysis-conversation-view', 'disabled'],
    queryFn: () => apiClient.request<AnalysisConversationView>(
      `/api/v1/workspaces/${workspaceId}/analysis-conversations/${conversationId}/view`,
    ),
    enabled: Boolean(workspaceId && conversationId),
    refetchInterval: (query) => {
      const view = query.state.data
      const latest = view?.turns.at(-1)?.analysis.run.status
      return latest && ['queued', 'running'].includes(latest) ? 1000 : false
    },
  })
}

export function useAnalysisConversationCommands(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  const refresh = async (conversation: AnalysisConversation): Promise<void> => {
    if (!workspaceId) return
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: analysisConversationKeys.all(workspaceId) }),
      queryClient.invalidateQueries({
        queryKey: analysisConversationKeys.view(workspaceId, conversation.id),
      }),
    ])
  }
  const create = useMutation({
    mutationFn: (input: { message: string; idempotencyKey: string }) =>
      apiClient.request<AnalysisConversation>(
        `/api/v1/workspaces/${workspaceId}/analysis-conversations`,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': input.idempotencyKey },
          body: JSON.stringify({ message: input.message }),
        },
      ),
    onSuccess: refresh,
  })
  const message = useMutation({
    mutationFn: (input: {
      conversationId: string
      message: string
      idempotencyKey: string
    }) => apiClient.request<AnalysisConversation>(
      `/api/v1/workspaces/${workspaceId}/analysis-conversations/${input.conversationId}/messages`,
      {
        method: 'POST',
        headers: { 'Idempotency-Key': input.idempotencyKey },
        body: JSON.stringify({ message: input.message }),
      },
    ),
    onSuccess: refresh,
  })
  return { create, message }
}
