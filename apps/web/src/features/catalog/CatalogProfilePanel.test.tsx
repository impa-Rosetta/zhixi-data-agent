import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import type { CatalogProfileList, CatalogSnapshot } from '../../lib/api/types'
import { CatalogProfilePanel } from './CatalogProfilePanel'

const snapshot: CatalogSnapshot = {
  id: 'snapshot-5', data_source_id: 'source-1', version: 5, status: 'published', database_product: 'PostgreSQL',
  database_version: '16.4', scan_options: {}, object_counts: {}, content_digest: 'five', sampling_enabled: true,
  profiling_status: 'succeeded', profiling_error_code: null, profiling_options: {}, profile_counts: { columns: 2, samples: 2 },
  profiling_started_at: '2026-09-06T01:00:00Z', profiling_finished_at: '2026-09-06T01:00:03Z',
  started_at: '2026-09-06T00:59:00Z', completed_at: '2026-09-06T00:59:03Z',
}

const profiles: CatalogProfileList = {
  snapshot_id: snapshot.id, profiling_status: 'succeeded', profiling_error_code: null,
  profile_counts: { columns: 2, samples: 2, sample_bytes: 18, budget_exhausted: false },
  items: [{
    id: 'profile-1', column_id: 'column-1', schema_name: 'public', relation_name: 'production_orders',
    column_name: 'product_code', data_type: 'string', native_type: 'text', sample_row_count: 20,
    non_null_count: 19, estimated_row_count: 1000, sample_null_rate: 0.05, sampled_distinct_count: 4,
    minimum_value: null, maximum_value: null, minimum_length: 6, maximum_length: 9, average_length: 7.2,
    sensitivity_type: null, sensitivity_confidence: 0, sensitivity_reasons: [], metric_sources: { null_rate: 'sampled' },
    samples: [{ ordinal: 0, masked_value: 'MOTOR-A', value_type: 'string', byte_count: 7 }],
  }, {
    id: 'profile-2', column_id: 'column-2', schema_name: 'public', relation_name: 'customers',
    column_name: 'email', data_type: 'string', native_type: 'text', sample_row_count: 20,
    non_null_count: 20, estimated_row_count: 200, sample_null_rate: 0, sampled_distinct_count: 20,
    minimum_value: null, maximum_value: null, minimum_length: null, maximum_length: null, average_length: null,
    sensitivity_type: 'email', sensitivity_confidence: 0.99, sensitivity_reasons: ['column_name'],
    metric_sources: { sensitivity: 'deterministic' }, samples: [],
  }],
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><CatalogProfilePanel workspaceId="workspace-1" dataSourceId="source-1" snapshots={[snapshot]} /></QueryClientProvider>)
}

test('shows bounded profile metrics and masked samples', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue(profiles)
  renderPanel()

  expect(await screen.findByRole('heading', { name: 'product_code' })).toBeInTheDocument()
  expect(screen.getByText('5.0%')).toBeInTheDocument()
  expect(screen.getByText('MOTOR-A')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /email.*敏感字段/ }))
  expect(screen.getByRole('heading', { name: 'email' })).toBeInTheDocument()
  expect(screen.getByText('邮箱')).toBeInTheDocument()
  expect(screen.getByText('敏感字段不保存或展示样例值')).toBeInTheDocument()
  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/data-sources/source-1/catalog/snapshots/snapshot-5/profiles',
  ))
})

test('explains the safe default when profiling is disabled', async () => {
  vi.spyOn(apiClient, 'request').mockResolvedValue({
    snapshot_id: snapshot.id, profiling_status: 'disabled', profiling_error_code: null, profile_counts: {}, items: [],
  })
  renderPanel()
  expect(await screen.findByText('当前快照未启用安全画像')).toBeInTheDocument()
})
