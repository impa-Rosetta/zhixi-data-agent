import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { ApiError, apiClient } from '../../lib/api/client'
import type { Catalog, SamplingPolicy } from '../../lib/api/types'
import { DataSourcePoliciesPanel } from './DataSourcePoliciesPanel'

const catalog: Catalog = {
  snapshot: {
    id: 'snapshot-5', data_source_id: 'source-1', version: 5, status: 'published', database_product: 'PostgreSQL',
    database_version: '16.4', scan_options: {}, object_counts: {}, content_digest: 'x', sampling_enabled: false,
    profiling_status: 'disabled', profiling_error_code: null, profiling_options: {}, profile_counts: {},
    profiling_started_at: null, profiling_finished_at: null, started_at: '2026-09-06T00:00:00Z', completed_at: '2026-09-06T00:00:01Z',
  },
  schemas: [{ name: 'public', comment: null, relations: [
    { name: 'production_orders', relation_type: 'table', comment: null, columns: [], constraints: [], indexes: [] },
    { name: 'order_summary', relation_type: 'view', comment: null, columns: [], constraints: [], indexes: [] },
  ] }],
}
const policy: SamplingPolicy = {
  data_source_id: 'source-1', enabled: false, schema_allowlist: [], table_allowlist: [],
  max_rows_per_table: 20, max_values_per_column: 20, max_value_chars: 256,
  max_bytes_per_table: 65536, max_bytes_per_job: 1048576, statement_timeout_seconds: 10,
  version: 2, updated_at: null,
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><DataSourcePoliciesPanel workspaceId="workspace-1" dataSourceId="source-1" snapshotId="snapshot-5" /></QueryClientProvider>)
}

test('saves an explicit table-scoped sampling policy', async () => {
  const request = vi.spyOn(apiClient, 'request').mockImplementation((path, init) => {
    if (path.endsWith('/sampling-policy') && init?.method === 'PUT') return Promise.resolve({ ...policy, enabled: true, version: 3 })
    if (path.endsWith('/sampling-policy')) return Promise.resolve(policy)
    if (path.endsWith('/schedule')) return Promise.reject(new ApiError(404, 'not configured', 'schedule.not_configured'))
    return Promise.resolve(catalog)
  })
  renderPanel()
  fireEvent.click(await screen.findByLabelText('启用安全采样'))
  fireEvent.click(screen.getByLabelText('允许采样 public.production_orders'))
  fireEvent.change(screen.getByLabelText('每表最大行数'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: '保存采样策略' }))

  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/data-sources/source-1/sampling-policy',
    expect.objectContaining({ method: 'PUT', body: JSON.stringify({ version: 2, enabled: true, schema_allowlist: ['public'], table_allowlist: [{ schema_name: 'public', table_name: 'production_orders' }], max_rows_per_table: 5, max_values_per_column: 20, max_value_chars: 256, max_bytes_per_table: 65536, max_bytes_per_job: 1048576, statement_timeout_seconds: 10 }) }),
  ))
})

test('creates a timezone-aware daily refresh schedule', async () => {
  const request = vi.spyOn(apiClient, 'request').mockImplementation((path, init) => {
    if (path.endsWith('/schedule') && init?.method === 'PUT') return Promise.resolve({ data_source_id: 'source-1', enabled: true, frequency: 'daily', timezone: 'Asia/Shanghai', local_time: '03:30:00', day_of_week: null, next_run_at: '2026-09-07T19:30:00Z', last_enqueued_at: null, version: 1, updated_at: null })
    if (path.endsWith('/schedule')) return Promise.reject(new ApiError(404, 'not configured', 'schedule.not_configured'))
    if (path.endsWith('/sampling-policy')) return Promise.resolve(policy)
    return Promise.resolve(catalog)
  })
  renderPanel()
  fireEvent.click(await screen.findByLabelText('启用定时刷新'))
  fireEvent.click(screen.getByRole('button', { name: '保存刷新计划' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/data-sources/source-1/schedule',
    expect.objectContaining({ method: 'PUT', body: JSON.stringify({ version: 0, enabled: true, frequency: 'daily', timezone: 'Asia/Shanghai', local_time: '03:30:00', day_of_week: null }) }),
  ))
})
