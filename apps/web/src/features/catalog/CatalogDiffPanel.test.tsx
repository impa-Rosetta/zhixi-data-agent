import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import type { CatalogDiffPage, CatalogSnapshot } from '../../lib/api/types'
import { CatalogDiffPanel } from './CatalogDiffPanel'

const snapshots: CatalogSnapshot[] = [{
  id: 'snapshot-2', data_source_id: 'source-1', version: 2, status: 'published', database_product: 'PostgreSQL',
  database_version: '16.4', scan_options: {}, object_counts: {}, content_digest: 'two', sampling_enabled: false,
  profiling_status: 'disabled', profiling_error_code: null, profiling_options: {}, profile_counts: {},
  profiling_started_at: null, profiling_finished_at: null, started_at: '2026-09-06T01:00:00Z', completed_at: '2026-09-06T01:00:03Z',
}, {
  id: 'snapshot-1', data_source_id: 'source-1', version: 1, status: 'published', database_product: 'PostgreSQL',
  database_version: '16.4', scan_options: {}, object_counts: {}, content_digest: 'one', sampling_enabled: false,
  profiling_status: 'disabled', profiling_error_code: null, profiling_options: {}, profile_counts: {},
  profiling_started_at: null, profiling_finished_at: null, started_at: '2026-09-06T00:00:00Z', completed_at: '2026-09-06T00:00:03Z',
}]

const page: CatalogDiffPage = {
  total: 3, limit: 50, offset: 0,
  items: [
    { id: 'diff-1', from_snapshot_id: 'snapshot-1', to_snapshot_id: 'snapshot-2', change_type: 'added', object_type: 'column', object_key: 'public.orders/column/priority', severity: 'info', before_value: null, after_value: { data_type: 'integer', nullable: true } },
    { id: 'diff-2', from_snapshot_id: 'snapshot-1', to_snapshot_id: 'snapshot-2', change_type: 'removed', object_type: 'index', object_key: 'public.orders/index/old_idx', severity: 'warning', before_value: { columns: ['created_at'] }, after_value: null },
    { id: 'diff-3', from_snapshot_id: 'snapshot-1', to_snapshot_id: 'snapshot-2', change_type: 'changed', object_type: 'column', object_key: 'public.orders/column/status', severity: 'breaking', before_value: { nullable: true }, after_value: { nullable: false } },
  ],
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><CatalogDiffPanel workspaceId="workspace-1" dataSourceId="source-1" snapshots={snapshots} /></QueryClientProvider>)
}

test('shows deterministic changes with severity and before-after details', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue(page)
  renderPanel()

  expect(await screen.findByText('public.orders/column/priority')).toBeInTheDocument()
  expect(screen.getByText('3 项变化')).toBeInTheDocument()
  expect(screen.getAllByText('破坏性')).toHaveLength(2)
  const changed = screen.getByText('public.orders/column/status').closest('details')
  if (!changed) throw new Error('Changed diff details were not rendered')
  fireEvent.click(within(changed).getByText('public.orders/column/status'))
  expect(within(changed).getByText(/"nullable": true/)).toBeInTheDocument()
  expect(within(changed).getByText(/"nullable": false/)).toBeInTheDocument()
  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/data-sources/source-1/diffs?to_snapshot_id=snapshot-2&limit=50&offset=0',
  ))
})

test('filters the loaded page without changing server evidence', async () => {
  vi.spyOn(apiClient, 'request').mockResolvedValue(page)
  renderPanel()
  await screen.findByText('public.orders/column/priority')

  fireEvent.change(screen.getByLabelText('变化类型'), { target: { value: 'removed' } })

  expect(screen.getByText('public.orders/index/old_idx')).toBeInTheDocument()
  expect(screen.queryByText('public.orders/column/priority')).not.toBeInTheDocument()
  expect(screen.getByText('当前筛选 1 项')).toBeInTheDocument()
})
