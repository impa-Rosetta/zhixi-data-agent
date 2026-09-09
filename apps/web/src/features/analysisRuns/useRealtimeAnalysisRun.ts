import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { analysisRunKeys, useAnalysisRunView } from './api'
import {
  applyAnalysisEvent,
  createAnalysisRunStreamState,
  type AnalysisRunStreamState,
} from './state'
import { watchAnalysisEvents } from './stream'

export type StreamConnection = 'idle' | 'connecting' | 'live' | 'closed' | 'error'

type BoundStreamState = {
  runId: string
  value: AnalysisRunStreamState
}

type ConnectionState = {
  runId: string
  value: StreamConnection
  error: string | null
}

const lightweightEvents = new Set(['run.created', 'run.node'])

export function useRealtimeAnalysisRun(
  workspaceId: string | undefined,
  runId: string | undefined,
) {
  const queryClient = useQueryClient()
  const query = useAnalysisRunView(workspaceId, runId)
  const [streamState, setStreamState] = useState<BoundStreamState | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState | null>(null)
  const lastSequence = useRef(0)

  useEffect(() => {
    if (!workspaceId || !runId || !query.data) return
    const controller = new AbortController()
    lastSequence.current = query.data.last_event_sequence
    const connect = async () => {
      await Promise.resolve()
      if (controller.signal.aborted) return
      setConnectionState({ runId, value: 'connecting', error: null })
      try {
        await watchAnalysisEvents(
          workspaceId,
          runId,
          query.data.last_event_sequence,
          async (event) => {
            const hasGap = event.sequence !== lastSequence.current + 1
            lastSequence.current = Math.max(lastSequence.current, event.sequence)
            setConnectionState({ runId, value: 'live', error: null })
            setStreamState((current) => {
              const base = current?.runId === runId
                ? current.value
                : createAnalysisRunStreamState(query.data)
              return { runId, value: applyAnalysisEvent(base, event) }
            })
            if (hasGap || !lightweightEvents.has(event.event_type)) {
              await queryClient.invalidateQueries({
                queryKey: analysisRunKeys.view(workspaceId, runId),
              })
              await queryClient.invalidateQueries({
                queryKey: analysisRunKeys.all(workspaceId),
              })
            }
          },
          controller.signal,
        )
        if (!controller.signal.aborted) {
          setConnectionState({ runId, value: 'closed', error: null })
        }
      } catch (reason: unknown) {
        if (controller.signal.aborted) return
        setConnectionState({
          runId,
          value: 'error',
          error: reason instanceof Error
            ? reason.message
            : 'analysis_event.connection_failed',
        })
      }
    }
    void connect()
    return () => controller.abort()
  }, [query.data, queryClient, runId, workspaceId])

  const projection = streamState && streamState.runId === runId
    ? streamState.value
    : null
  const data = projection && projection.view.last_event_sequence > (query.data?.last_event_sequence ?? -1)
    ? projection.view
    : query.data
  const activeConnection = connectionState && connectionState.runId === runId
    ? connectionState
    : null
  const connection = activeConnection
    ? activeConnection.value
    : 'idle'

  return {
    ...query,
    data,
    events: projection?.events ?? [],
    connection,
    streamError: activeConnection?.error ?? null,
  }
}
