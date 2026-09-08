import { apiClient } from '../../lib/api/client'
import type { AnalysisEvent } from './types'

type EventHandler = (event: AnalysisEvent) => void | Promise<void>

function parseFrame(frame: string): AnalysisEvent | null {
  let id: number | null = null
  let eventName = ''
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator < 0 ? line : line.slice(0, separator)
    const rawValue = separator < 0 ? '' : line.slice(separator + 1)
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
    if (field === 'id') id = Number(value)
    else if (field === 'event') eventName = value
    else if (field === 'data') data.push(value)
  }
  if (data.length === 0) return null
  const parsed = JSON.parse(data.join('\n')) as Partial<AnalysisEvent>
  if (
    !Number.isInteger(id) ||
    !Number.isInteger(parsed.sequence) ||
    typeof parsed.event_type !== 'string' ||
    typeof parsed.created_at !== 'string' ||
    parsed.payload === null ||
    typeof parsed.payload !== 'object' ||
    Array.isArray(parsed.payload)
  ) {
    throw new Error('analysis_event.invalid')
  }
  if (id !== parsed.sequence) throw new Error('analysis_event.sequence_mismatch')
  if (eventName && eventName !== parsed.event_type) {
    throw new Error('analysis_event.type_mismatch')
  }
  return parsed as AnalysisEvent
}

export async function consumeSse(
  response: Response,
  onEvent: EventHandler,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.headers.get('Content-Type')?.startsWith('text/event-stream')) {
    throw new Error('analysis_event.invalid_content_type')
  }
  if (!response.body) throw new Error('analysis_event.missing_body')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = /\r?\n\r?\n/.exec(buffer)
      while (boundary?.index !== undefined) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const event = parseFrame(frame)
        if (event) await onEvent(event)
        boundary = /\r?\n\r?\n/.exec(buffer)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export async function connectAnalysisEventStream(
  workspaceId: string,
  runId: string,
  after: number,
  onEvent: EventHandler,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiClient.requestStream(
    `/api/v1/workspaces/${workspaceId}/analysis-runs/${runId}/events/stream`,
    {
      headers: { 'Last-Event-ID': String(Math.max(0, after)) },
      signal,
    },
  )
  await consumeSse(response, onEvent, signal)
}

function terminalEvent(event: AnalysisEvent): boolean {
  if (
    event.event_type === 'run.completed' ||
    event.event_type === 'run.cancelled' ||
    event.event_type === 'run.confirmation_rejected'
  ) {
    return true
  }
  return event.event_type === 'run.failed' && event.payload.retryable !== true
}

function abortableDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve()
      return
    }
    const onAbort = () => {
      window.clearTimeout(timer)
      resolve()
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, milliseconds)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export async function watchAnalysisEvents(
  workspaceId: string,
  runId: string,
  initialSequence: number,
  onEvent: EventHandler,
  signal?: AbortSignal,
): Promise<void> {
  let cursor = Math.max(0, initialSequence)
  let retryDelay = 500
  while (!signal?.aborted) {
    let reachedTerminal = false
    try {
      await connectAnalysisEventStream(
        workspaceId,
        runId,
        cursor,
        async (event) => {
          if (event.sequence <= cursor) return
          cursor = event.sequence
          reachedTerminal ||= terminalEvent(event)
          await onEvent(event)
        },
        signal,
      )
      if (reachedTerminal || signal?.aborted) return
      retryDelay = 500
    } catch (reason) {
      if (signal?.aborted) return
      if (
        reason instanceof Error &&
        reason.message.startsWith('analysis_event.') &&
        reason.message !== 'analysis_event.missing_body'
      ) {
        throw reason
      }
    }
    await abortableDelay(retryDelay, signal)
    retryDelay = Math.min(retryDelay * 2, 10_000)
  }
}
