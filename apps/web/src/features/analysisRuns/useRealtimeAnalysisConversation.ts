import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import {
  analysisConversationKeys,
  useAnalysisConversationView,
} from './conversationApi'
import { watchConversationEvents } from './stream'
import type { StreamConnection } from './useRealtimeAnalysisRun'

export function useRealtimeAnalysisConversation(
  workspaceId: string | undefined,
  conversationId: string | undefined,
) {
  const queryClient = useQueryClient()
  const query = useAnalysisConversationView(workspaceId, conversationId)
  const [connection, setConnection] = useState<StreamConnection>('idle')
  const [streamError, setStreamError] = useState<string | null>(null)
  const cursor = useRef(0)
  const lastEventSequence = query.data?.conversation.last_event_sequence

  useEffect(() => {
    if (!workspaceId || !conversationId || lastEventSequence === undefined) return
    const controller = new AbortController()
    cursor.current = lastEventSequence
    queueMicrotask(() => {
      if (controller.signal.aborted) return
      setConnection('connecting')
      setStreamError(null)
    })
    void watchConversationEvents(
      workspaceId,
      conversationId,
      cursor.current,
      async (event) => {
        const hasGap = event.sequence !== cursor.current + 1
        cursor.current = Math.max(cursor.current, event.sequence)
        setConnection('live')
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: analysisConversationKeys.view(workspaceId, conversationId),
          }),
          queryClient.invalidateQueries({
            queryKey: analysisConversationKeys.page(workspaceId),
          }),
        ])
        if (hasGap) {
          await queryClient.refetchQueries({
            queryKey: analysisConversationKeys.view(workspaceId, conversationId),
          })
        }
      },
      controller.signal,
    ).catch((reason: unknown) => {
      if (controller.signal.aborted) return
      setConnection('error')
      setStreamError(reason instanceof Error ? reason.message : 'conversation_event.connection_failed')
    })
    return () => controller.abort()
  }, [conversationId, lastEventSequence, queryClient, workspaceId])

  return { ...query, connection, streamError }
}
