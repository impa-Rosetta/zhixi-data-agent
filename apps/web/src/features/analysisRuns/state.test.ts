import { expect, test } from 'vitest'

import { applyAnalysisEvent, createAnalysisRunStreamState } from './state'
import type { AnalysisEvent, AnalysisRunView } from './types'

function view(lastSequence = 1): AnalysisRunView {
  return {
    run: {
      id: 'run-1',
      workspace_id: 'workspace-1',
      status: 'queued',
      current_node: 'understand',
      context: {},
      frozen_versions: {},
      budget: {},
      model_calls: 0,
      tool_calls: 0,
      total_tokens: 0,
      replan_count: 0,
      error_code: null,
      version: 1,
      cancel_requested_at: null,
      started_at: null,
      created_at: '2026-09-08T00:00:00Z',
      updated_at: '2026-09-08T00:00:00Z',
      finished_at: null,
    },
    messages: [],
    plan: null,
    steps: [],
    tool_calls: [],
    artifacts: [],
    evidence: [],
    validations: [],
    last_event_sequence: lastSequence,
  }
}

function event(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown> = {},
): AnalysisEvent {
  return {
    sequence,
    event_type: eventType,
    payload,
    created_at: '2026-09-08T00:00:00Z',
  }
}

test('ignores replayed events and applies known node state monotonically', () => {
  const initial = createAnalysisRunStreamState(view())
  const duplicate = applyAnalysisEvent(initial, event(1, 'run.created'))
  const updated = applyAnalysisEvent(
    duplicate,
    event(2, 'run.node', { node: 'bind', status: 'running' }),
  )

  expect(duplicate).toBe(initial)
  expect(updated.lastSequence).toBe(2)
  expect(updated.view.run).toMatchObject({ current_node: 'bind', status: 'running' })
  expect(updated.needsProjectionRefresh).toBe(false)
})

test('marks an event sequence gap for authoritative projection recovery', () => {
  const updated = applyAnalysisEvent(
    createAnalysisRunStreamState(view()),
    event(3, 'run.node', { node: 'plan' }),
  )

  expect(updated.lastSequence).toBe(3)
  expect(updated.needsProjectionRefresh).toBe(true)
})

test('keeps unknown events in the technical timeline without changing run state', () => {
  const initial = createAnalysisRunStreamState(view())
  const updated = applyAnalysisEvent(initial, event(2, 'future.event', { arbitrary: true }))

  expect(updated.view.run).toEqual(initial.view.run)
  expect(updated.events).toHaveLength(1)
  expect(updated.needsProjectionRefresh).toBe(false)
})
