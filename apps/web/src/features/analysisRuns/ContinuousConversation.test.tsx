import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { AnalysisConversationView, AnalysisRunStatus } from './types'
import { ContinuousConversation } from './ContinuousConversation'

function view(status: AnalysisRunStatus): AnalysisConversationView {
  const now = '2026-09-15T10:00:00Z'
  return {
    conversation: {
      id: 'conversation-1',
      workspace_id: 'workspace-1',
      title: '不良率分析',
      status: 'active',
      context: { version: 1 },
      active_turn_id: 'turn-1',
      last_turn_sequence: 1,
      last_event_sequence: 0,
      version: 1,
      created_at: now,
      updated_at: now,
      archived_at: null,
    },
    turns: [{
      turn: {
        id: 'turn-1',
        sequence: 1,
        parent_turn_id: null,
        analysis_run_id: 'run-1',
        relation: 'initial',
        status: status === 'completed' ? 'completed' : 'running',
        queued_at: now,
        started_at: now,
        finished_at: status === 'completed' ? now : null,
        created_at: now,
        updated_at: now,
      },
      analysis: {
        run: {
          id: 'run-1',
          workspace_id: 'workspace-1',
          status,
          current_node: status === 'completed' ? 'present' : 'execute',
          context: { goal: '不良率是多少？' },
          frozen_versions: {},
          budget: {},
          model_calls: 1,
          tool_calls: 0,
          total_tokens: 10,
          replan_count: 0,
          error_code: null,
          version: 1,
          cancel_requested_at: null,
          started_at: now,
          created_at: now,
          updated_at: now,
          finished_at: status === 'completed' ? now : null,
        },
        messages: [
          { id: 'm1', role: 'user', content: '不良率是多少？', context_patch: {}, created_at: now },
          { id: 'm2', role: 'assistant', content: '不良率为 2.4%。', context_patch: {}, created_at: now },
        ],
        plan: null,
        steps: [],
        tool_calls: [],
        artifacts: [],
        evidence: [],
        validations: [],
        last_event_sequence: 2,
      },
      suggested_follow_ups: [],
    }],
    total_turns: 1,
    limit: 20,
    offset: 0,
    read_only: false,
    legacy_run_id: null,
  }
}

test('keeps the bottom composer available after an answer completes', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <ContinuousConversation
      view={view('completed')}
      busy={false}
      error={null}
      onSubmit={onSubmit}
    />,
  )

  expect(screen.getByText('不良率为 2.4%。')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('继续追问'), { target: { value: '按月份展开' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))

  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('按月份展开'))
})

test('allows another message while the agent is running and labels it as queued', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <ContinuousConversation
      view={view('running')}
      busy={false}
      error={null}
      onSubmit={onSubmit}
    />,
  )

  fireEvent.change(screen.getByLabelText('继续追问'), { target: { value: '再比较上个月' } })
  fireEvent.click(screen.getByRole('button', { name: '加入队列' }))

  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('再比较上个月'))
  expect(screen.getByText('Agent 正在处理，发送后将自动排队')).toBeInTheDocument()
})

test('cancels the active running turn without disabling the conversation composer', async () => {
  const onCancel = vi.fn().mockResolvedValue(undefined)
  render(
    <ContinuousConversation
      view={view('running')}
      busy={false}
      error={null}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
      onCancel={onCancel}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: '取消当前分析' }))
  await waitFor(() => expect(onCancel).toHaveBeenCalledWith('turn-1'))
  expect(screen.getByLabelText('继续追问')).toBeEnabled()
})

test('shows topic switches and supports control-enter submission', async () => {
  const data = view('completed')
  data.turns[0].turn.relation = 'switch_topic'
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <ContinuousConversation
      view={data}
      busy={false}
      error={null}
      onSubmit={onSubmit}
    />,
  )

  expect(screen.getByText(/已切换到新的分析主题/)).toBeInTheDocument()
  const composer = screen.getByLabelText('继续追问')
  fireEvent.change(composer, { target: { value: '数据库有哪些表' } })
  fireEvent.keyDown(composer, { key: 'Enter', ctrlKey: true })
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('数据库有哪些表'))
})

test('sends a recommendation through the normal message callback with its audit id', async () => {
  const data = view('completed')
  data.turns[0].suggested_follow_ups = [{
    id: 'metric.trend',
    label: '查看月度趋势',
    message: '按月份展开不良率',
    source: 'metric_context',
  }]
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <ContinuousConversation
      view={data}
      busy={false}
      error={null}
      onSubmit={onSubmit}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: '查看月度趋势' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('按月份展开不良率', 'metric.trend'))
})
