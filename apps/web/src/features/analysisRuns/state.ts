import type { AnalysisEvent, AnalysisRunStatus, AnalysisRunView } from './types'

export type AnalysisRunStreamState = {
  view: AnalysisRunView
  events: AnalysisEvent[]
  lastSequence: number
  needsProjectionRefresh: boolean
}

export function createAnalysisRunStreamState(view: AnalysisRunView): AnalysisRunStreamState {
  return {
    view,
    events: [],
    lastSequence: view.last_event_sequence,
    needsProjectionRefresh: false,
  }
}

function knownStatus(event: AnalysisEvent): AnalysisRunStatus | null {
  const status = event.payload.status
  if (
    status === 'queued' ||
    status === 'running' ||
    status === 'waiting_for_clarification' ||
    status === 'waiting_for_confirmation' ||
    status === 'completed' ||
    status === 'failed_retryable' ||
    status === 'failed' ||
    status === 'cancelled'
  ) {
    return status
  }
  if (event.event_type === 'run.clarification_required') return 'waiting_for_clarification'
  if (event.event_type === 'run.confirmation_required') return 'waiting_for_confirmation'
  if (event.event_type === 'run.completed') return 'completed'
  if (
    event.event_type === 'run.cancelled' ||
    event.event_type === 'run.confirmation_rejected'
  ) {
    return 'cancelled'
  }
  if (event.event_type === 'run.failed') {
    return event.payload.retryable === true ? 'failed_retryable' : 'failed'
  }
  return null
}

function requiresProjection(event: AnalysisEvent): boolean {
  return [
    'message.accepted',
    'run.clarification_required',
    'run.confirmation_required',
    'run.confirmed',
    'run.confirmation_rejected',
    'run.completed',
    'run.failed',
    'run.cancelled',
  ].includes(event.event_type)
}

export function applyAnalysisEvent(
  state: AnalysisRunStreamState,
  event: AnalysisEvent,
): AnalysisRunStreamState {
  if (event.sequence <= state.lastSequence) return state
  const sequenceGap = event.sequence !== state.lastSequence + 1
  const status = knownStatus(event)
  const node = event.event_type === 'run.node' ? event.payload.node : null
  return {
    view: {
      ...state.view,
      run: {
        ...state.view.run,
        ...(status ? { status } : {}),
        ...(typeof node === 'string' ? { current_node: node } : {}),
      },
      last_event_sequence: event.sequence,
    },
    events: [...state.events.slice(-199), event],
    lastSequence: event.sequence,
    needsProjectionRefresh:
      state.needsProjectionRefresh || sequenceGap || requiresProjection(event),
  }
}
