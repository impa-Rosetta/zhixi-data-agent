import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import type { AnalysisConversationView } from '../analysisRuns/types'
import { ApiError } from '../../lib/api/client'
import { ConversationReports } from './ConversationReports'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  download: vi.fn(),
  preview: vi.fn(),
  retry: vi.fn(),
  reports: [] as Array<{
    id: string
    conversation_id: string
    title: string
    status: 'succeeded' | 'failed'
    error_code: string | null
    created_at: string
    spec: { sections: Array<{ source: { turn_id: string, evidence_ids: string[] } }> }
  }>,
}))

vi.mock('./api', () => ({
  useConversationReports: () => ({
    data: { items: mocks.reports, total: mocks.reports.length },
    isLoading: false,
    isError: false,
  }),
  useCreateConversationReport: () => ({
    mutateAsync: mocks.create,
    isPending: false,
  }),
  useRetryConversationReport: () => ({
    mutateAsync: mocks.retry,
    isPending: false,
  }),
  downloadReportFile: mocks.download,
  previewReportHtml: mocks.preview,
}))

function conversation(trusted: boolean): AnalysisConversationView {
  const now = '2026-09-25T00:00:00Z'
  return {
    conversation: {
      id: 'conversation-1',
      workspace_id: 'workspace-1',
      title: '不良率分析',
      status: 'active',
      context: {},
      active_turn_id: null,
      last_turn_sequence: 1,
      last_event_sequence: 1,
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
        status: 'completed',
        queued_at: now,
        started_at: now,
        finished_at: now,
        created_at: now,
        updated_at: now,
      },
      analysis: {
        run: {
          id: 'run-1',
          workspace_id: 'workspace-1',
          status: 'completed',
          current_node: 'present',
          context: {},
          frozen_versions: {},
          budget: {},
          model_calls: 1,
          tool_calls: 1,
          total_tokens: 10,
          replan_count: 0,
          error_code: null,
          version: 1,
          cancel_requested_at: null,
          started_at: now,
          finished_at: now,
          created_at: now,
          updated_at: now,
        },
        messages: [{ id: 'message-1', role: 'user', content: '最近不良率', context_patch: {}, created_at: now }],
        plan: null,
        steps: [],
        tool_calls: [],
        artifacts: trusted
          ? [{ id: 'artifact-1', artifact_type: 'query_result', summary: {}, content_digest: 'a', created_at: now }]
          : [],
        evidence: trusted
          ? [{ id: 'evidence-1', artifact_id: 'artifact-1', evidence_type: 'query_execution', reference: {}, evidence_digest: 'b', created_at: now }]
          : [],
        validations: trusted
          ? [{ id: 'validation-1', validation_type: 'evidence', outcome: 'passed', findings: [], created_at: now }]
          : [],
        last_event_sequence: 1,
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

beforeEach(() => {
  mocks.create.mockReset().mockResolvedValue({})
  mocks.download.mockReset()
  mocks.preview.mockReset().mockResolvedValue('<html><body>可信报告</body></html>')
  mocks.retry.mockReset().mockResolvedValue({})
  mocks.reports = []
})

test('offers real report creation only for trusted completed turns', async () => {
  render(<ConversationReports view={conversation(true)} />)
  expect(screen.getByLabelText(/第 1 轮/)).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: '生成报告' }))
  await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
    title: '不良率分析报告',
    turnIds: ['turn-1'],
  })))
})

test('explains invalid advanced evidence in natural language', async () => {
  mocks.create.mockRejectedValue(new ApiError(409, 'internal', 'report.advanced_lineage_invalid'))
  render(<ConversationReports view={conversation(true)} />)
  fireEvent.click(screen.getByRole('button', { name: '生成报告' }))
  expect(await screen.findByText('高级分析的来源权限或计算证据已失效，请重新查询和分析后生成报告。')).toBeInTheDocument()
  expect(screen.queryByText('internal')).not.toBeInTheDocument()
})

test('does not offer report creation for a chat answer without evidence', () => {
  render(<ConversationReports view={conversation(false)} />)
  expect(screen.queryByRole('button', { name: '生成报告' })).not.toBeInTheDocument()
  expect(screen.getByText(/没有同时具备数据结果、验证和证据/)).toBeInTheDocument()
})

test('shows server-confirmed report status and download formats', () => {
  mocks.reports = [{
    id: 'report-1',
    conversation_id: 'conversation-1',
    title: '质量报告',
    status: 'succeeded',
    error_code: null,
    created_at: '2026-09-25T00:00:00Z',
    spec: { sections: [{ source: { turn_id: 'turn-1', evidence_ids: ['evidence-1'] } }] },
  }]
  render(<ConversationReports view={conversation(true)} />)
  expect(screen.getByText('已生成')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Markdown' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'HTML' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'PDF' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '定位证据 1' })).toHaveAttribute('href', '#evidence-evidence-1')
})

test('renders server HTML only inside a script-blocking preview frame', async () => {
  mocks.reports = [{
    id: 'report-1',
    conversation_id: 'conversation-1',
    title: '质量报告',
    status: 'succeeded',
    error_code: null,
    created_at: '2026-09-25T00:00:00Z',
    spec: { sections: [{ source: { turn_id: 'turn-1', evidence_ids: ['evidence-1'] } }] },
  }]
  render(<ConversationReports view={conversation(true)} />)

  fireEvent.click(screen.getByRole('button', { name: '在线预览' }))

  const frame = await screen.findByTitle('质量报告预览')
  expect(mocks.preview).toHaveBeenCalledWith('workspace-1', 'report-1')
  expect(frame).toHaveAttribute('sandbox', '')
  expect(frame.getAttribute('srcdoc')).toContain("default-src 'none'")
  expect(frame.getAttribute('srcdoc')).toContain('可信报告')
  fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
  await waitFor(() => expect(screen.queryByTitle('质量报告预览')).not.toBeInTheDocument())
})

test('allows retry only for a recoverable report failure', async () => {
  mocks.reports = [{
    id: 'report-1',
    conversation_id: 'conversation-1',
    title: '质量报告',
    status: 'failed',
    error_code: 'report.storage_unavailable',
    created_at: '2026-09-25T00:00:00Z',
    spec: { sections: [{ source: { turn_id: 'turn-1', evidence_ids: ['evidence-1'] } }] },
  }]
  const { rerender } = render(<ConversationReports view={conversation(true)} />)

  fireEvent.click(screen.getByRole('button', { name: '重新尝试' }))
  await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith('report-1'))

  mocks.reports = [{ ...mocks.reports[0], error_code: 'report.spec_invalid' }]
  rerender(<ConversationReports view={conversation(true)} />)
  expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
})
