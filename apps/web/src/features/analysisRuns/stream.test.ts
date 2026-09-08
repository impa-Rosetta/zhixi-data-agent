import { afterEach, expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import {
  connectAnalysisEventStream,
  consumeSse,
  watchAnalysisEvents,
} from './stream'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

test('parses chunked CRLF events and ignores heartbeat comments', async () => {
  const encoder = new TextEncoder()
  const chunks = [
    ': keep-alive\r\n\r\nid: 1\r\nevent: run.created\r\ndata: {"sequence":1,',
    '"event_type":"run.created","payload":{"status":"queued"},',
    '"created_at":"2026-09-08T00:00:00Z"}\r\n\r\n',
  ]
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  const events: string[] = []

  await consumeSse(
    new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    (event) => {
      events.push(event.event_type)
    },
  )

  expect(events).toEqual(['run.created'])
})

test('rejects a frame whose SSE id disagrees with the persisted sequence', async () => {
  const response = new Response(
    'id: 2\nevent: run.created\ndata: {"sequence":1,"event_type":"run.created","payload":{},"created_at":"2026-09-08T00:00:00Z"}\n\n',
    { headers: { 'Content-Type': 'text/event-stream' } },
  )

  await expect(consumeSse(response, () => undefined)).rejects.toThrow(
    'analysis_event.sequence_mismatch',
  )
})

test('connects with the last applied event sequence and forwards parsed events', async () => {
  const request = vi.spyOn(apiClient, 'requestStream').mockResolvedValue(
    new Response(
      'id: 4\nevent: run.cancelled\ndata: {"sequence":4,"event_type":"run.cancelled","payload":{"status":"cancelled"},"created_at":"2026-09-08T00:00:00Z"}\n\n',
      { headers: { 'Content-Type': 'text/event-stream' } },
    ),
  )
  const events: number[] = []

  await connectAnalysisEventStream('workspace-1', 'run-1', 3, (event) => {
    events.push(event.sequence)
  })

  expect(request).toHaveBeenCalledOnce()
  expect(request.mock.calls[0]?.[0]).toBe(
    '/api/v1/workspaces/workspace-1/analysis-runs/run-1/events/stream',
  )
  expect(new Headers(request.mock.calls[0]?.[1]?.headers).get('Last-Event-ID')).toBe('3')
  expect(events).toEqual([4])
})

test('reconnects after an interrupted stream and deduplicates replayed events', async () => {
  vi.useFakeTimers()
  const response = (content: string) =>
    new Response(content, { headers: { 'Content-Type': 'text/event-stream' } })
  const request = vi.spyOn(apiClient, 'requestStream')
    .mockResolvedValueOnce(
      response(
        'id: 2\nevent: run.node\ndata: {"sequence":2,"event_type":"run.node","payload":{"node":"bind"},"created_at":"2026-09-08T00:00:00Z"}\n\n',
      ),
    )
    .mockResolvedValueOnce(
      response(
        'id: 2\nevent: run.node\ndata: {"sequence":2,"event_type":"run.node","payload":{"node":"bind"},"created_at":"2026-09-08T00:00:00Z"}\n\nid: 3\nevent: run.completed\ndata: {"sequence":3,"event_type":"run.completed","payload":{},"created_at":"2026-09-08T00:00:01Z"}\n\n',
      ),
    )
  const events: number[] = []
  const watching = watchAnalysisEvents('workspace-1', 'run-1', 1, (item) => {
    events.push(item.sequence)
  })

  await vi.advanceTimersByTimeAsync(500)
  await watching

  expect(events).toEqual([2, 3])
  expect(request).toHaveBeenCalledTimes(2)
})
