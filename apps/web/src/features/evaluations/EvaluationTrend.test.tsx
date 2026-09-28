import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { EvaluationRun } from './api'
import { EvaluationTrend } from './EvaluationTrend'

function run(id: string, overrides: Partial<EvaluationRun> = {}): EvaluationRun {
  return {
    id, workspace_id: 'workspace-1', track: 'offline', status: 'completed',
    suite_version: '0.1.19', suite_digest: 'a'.repeat(64), dataset_id: 'synthetic-1',
    semantic_version: 'semantic-1', model_version: 'offline-fixed-v1',
    tool_version: 'tools-1', prompt_version: 'prompts-1',
    summary: { coverage_rate: 1, evaluated_pass_rate: 0.75 }, budget: {},
    calls_used: 0, tokens_used: 0, attempt_count: 1, error_code: null,
    created_at: '2026-09-28T10:00:00Z', ...overrides,
  }
}

test('draws chronological trends only from comparable completed runs', () => {
  const current = run('new', { created_at: '2026-09-28T12:00:00Z' })
  const old = run('old', {
    created_at: '2026-09-28T09:00:00Z',
    summary: { coverage_rate: 0.5, evaluated_pass_rate: 0.25 },
  })
  render(<EvaluationTrend current={current} recent={[
    current,
    run('different-model', { model_version: 'live-v1' }),
    run('running', { status: 'running' }),
    old,
  ]} />)

  expect(screen.getByRole('img', { name: '最近同版本评测覆盖率与已评估通过率趋势' })).toBeVisible()
  expect(screen.getByRole('row', { name: /50\.0%.*25\.0%/ })).toBeVisible()
  expect(screen.getByRole('row', { name: /100\.0%.*75\.0%/ })).toBeVisible()
  expect(screen.getAllByRole('row')).toHaveLength(3)
  expect(document.querySelector('.evaluation-trend-coverage')).toHaveAttribute('points', '20,70 580,20')
  expect(document.querySelector('.evaluation-trend-pass')).toHaveAttribute('points', '20,95 580,45')
})

test('refuses to join different frozen versions or invalid rates into a trend', () => {
  const current = run('new')
  render(<EvaluationTrend current={current} recent={[
    current,
    run('other-suite', { suite_digest: 'b'.repeat(64) }),
    run('other-tool', { tool_version: 'tools-2' }),
    run('invalid-rate', { summary: { coverage_rate: 1.5, evaluated_pass_rate: 0.5 } }),
  ]} />)

  expect(screen.getByText('暂无可比趋势')).toBeVisible()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

test.each([
  { workspace_id: 'other-workspace' }, { track: 'live' as const },
  { suite_version: '0.1.20' }, { suite_digest: 'b'.repeat(64) },
  { dataset_id: 'other-data' }, { semantic_version: 'other-semantic' },
  { model_version: 'other-model' }, { tool_version: 'other-tool' },
  { prompt_version: 'other-prompt' },
])('does not mix frozen context %j', (changed) => {
  const current = run('new')
  render(<EvaluationTrend current={current} recent={[current, run('old', changed)]} />)
  expect(screen.getByText('暂无可比趋势')).toBeVisible()
})

test.each([undefined, null, '0.9', Number.NaN, Number.POSITIVE_INFINITY, -0.1, 1.1])(
  'does not invent a rate from %s', (invalid) => {
    const current = run('new')
    render(<EvaluationTrend current={current} recent={[
      current, run('old', { summary: { coverage_rate: invalid, evaluated_pass_rate: 0.5 } }),
    ]} />)
    expect(screen.getByText('暂无可比趋势')).toBeVisible()
  },
)

test('keeps the latest thirty scope even when an older comparable record exists', () => {
  const current = run('new')
  const other = Array.from({ length: 29 }, (_, index) => run(`other-${index}`, { track: 'live' }))
  render(<EvaluationTrend current={current} recent={[current, ...other, run('too-old')]} />)
  expect(screen.getByText('暂无可比趋势')).toBeVisible()
})

test('accepts genuine zero and full rates without fabricating gaps', () => {
  const current = run('new', { summary: { coverage_rate: 0, evaluated_pass_rate: 0 } })
  render(<EvaluationTrend current={current} recent={[
    current, run('old', { summary: { coverage_rate: 1, evaluated_pass_rate: 1 } }),
  ]} />)
  expect(screen.getAllByText('0.0%')).toHaveLength(2)
  expect(screen.getAllByText('100.0%')).toHaveLength(2)
})
