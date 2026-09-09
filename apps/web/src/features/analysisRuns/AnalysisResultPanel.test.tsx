import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { AnalysisResultPanel } from './AnalysisResultPanel'
import { AnalysisInspector } from './AnalysisInspector'
import type { AnalysisRunView } from './types'

function resultView(summary: Record<string, unknown>): AnalysisRunView {
  return {
    run: {
      id: 'run-1', workspace_id: 'workspace-1', status: 'completed', current_node: 'present',
      context: {}, frozen_versions: { semantic_version_id: 'semantic-v1' }, budget: {},
      model_calls: 1, tool_calls: 1, total_tokens: 30, replan_count: 0, error_code: null,
      version: 3, cancel_requested_at: null, started_at: null,
      created_at: '2026-09-09T00:00:00Z', updated_at: '2026-09-09T00:01:00Z',
      finished_at: '2026-09-09T00:01:00Z',
    },
    messages: [], plan: null, steps: [], tool_calls: [],
    artifacts: [{
      id: 'artifact-1', artifact_type: 'query_result', summary,
      content_digest: 'a'.repeat(64), created_at: '2026-09-09T00:01:00Z',
    }],
    evidence: [{
      id: 'evidence-1', artifact_id: 'artifact-1', evidence_type: 'query_execution',
      reference: {
        validated_query_id: 'query-1', execution_id: 'execution-1',
        semantic_version_id: 'semantic-v1', snapshot_ids: ['snapshot-1'], trust: 'trusted',
      },
      evidence_digest: 'b'.repeat(64), created_at: '2026-09-09T00:01:00Z',
    }],
    validations: [{
      id: 'validation-1', validation_type: 'evidence', outcome: 'passed', findings: [],
      created_at: '2026-09-09T00:01:00Z',
    }],
    last_event_sequence: 5,
  }
}

test('renders a trusted metric result and evidence locator', () => {
  render(<AnalysisResultPanel view={resultView({
    columns: ['defect_rate'], rows: [[2.5]], row_count: 1,
    truncated: false, trust: 'trusted', evidence_digest: 'b'.repeat(64),
  })} />)

  expect(screen.getByText('可信结果')).toBeInTheDocument()
  expect(screen.getByText('defect_rate')).toBeInTheDocument()
  expect(screen.getByText('2.5')).toBeInTheDocument()
  expect(screen.getByText('1 行')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '定位证据' })).toHaveAttribute('href', '#evidence-evidence-1')
})

test('renders truncation and hostile values without object stringification', () => {
  render(<AnalysisResultPanel view={resultView({
    columns: ['line', 'payload'], rows: [['A', { nested: true }]],
    row_count: 201, truncated: true, trust: 'exploratory',
  })} />)

  expect(screen.getByText('探索结果')).toBeInTheDocument()
  expect(screen.getByText('结果已截断')).toBeInTheDocument()
  expect(screen.getByText('201 行')).toBeInTheDocument()
  expect(screen.queryByText('[object Object]')).not.toBeInTheDocument()
})

test('shows immutable evidence references and validation outcome', () => {
  const view = resultView({ columns: ['defect_rate'], rows: [[2.5]], trust: 'trusted' })
  render(<AnalysisInspector view={view} events={[]} connection="closed" streamError={null} />)

  expect(screen.getByText('查询执行证据')).toBeInTheDocument()
  expect(screen.getByTitle('query-1')).toHaveTextContent('query-1')
  expect(screen.getByTitle('semantic-v1')).toHaveTextContent('semantic-v1')
  expect(screen.getByText('证据完整性')).toBeInTheDocument()
  expect(screen.getByText('通过 · 0 个发现')).toBeInTheDocument()
})
