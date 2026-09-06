import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../features/auth/context'
import { apiClient } from '../lib/api/client'
import type { Catalog, CatalogSnapshot, DataSource, SamplingPolicy, ScanJob, ScanSchedule } from '../lib/api/types'
import { DataSourceDetailPage } from './DataSourceDetailPage'

const source: DataSource = {
  id: 'source-1', workspace_id: 'workspace-1', name: '生产库', description: '制造数据', source_type: 'postgresql',
  host: 'source-postgres', port: 5432, database_name: 'factory_demo', tls_mode: 'disable', network_policy_id: null,
  status: 'ready', health_code: null, active_snapshot_id: 'snapshot-1', version: 2,
  last_checked_at: '2026-09-06T01:00:00Z', last_success_at: '2026-09-06T01:00:00Z',
  created_at: '2026-09-06T00:00:00Z', updated_at: '2026-09-06T01:00:00Z',
}
const job: ScanJob = {
  id: 'job-1', data_source_id: 'source-1', snapshot_id: 'snapshot-1', parent_job_id: null, retry_of_job_id: null,
  job_type: 'metadata_scan', trigger: 'manual', status: 'succeeded', phase: 'published', progress: 100,
  error_code: null, created_at: '2026-09-06T00:30:00Z', started_at: '2026-09-06T00:30:01Z',
  heartbeat_at: '2026-09-06T00:30:02Z', cancel_requested_at: null, finished_at: '2026-09-06T00:30:03Z',
}
const snapshot: CatalogSnapshot = {
  id: 'snapshot-1', data_source_id: 'source-1', version: 1, status: 'published', database_product: 'PostgreSQL',
  database_version: '16.4', scan_options: {}, object_counts: { schemas: 1, relations: 2, columns: 12 },
  content_digest: 'abc', sampling_enabled: false, profiling_status: 'disabled', profiling_error_code: null,
  profiling_options: {}, profile_counts: {}, profiling_started_at: null, profiling_finished_at: null,
  started_at: '2026-09-06T00:30:00Z', completed_at: '2026-09-06T00:30:03Z',
}

const catalog: Catalog = { snapshot, schemas: [] }
const policy: SamplingPolicy = {
  data_source_id: 'source-1', enabled: false, schema_allowlist: [], table_allowlist: [],
  max_rows_per_table: 10, max_values_per_column: 5, max_value_chars: 128,
  max_bytes_per_table: 65536, max_bytes_per_job: 262144, statement_timeout_seconds: 3,
  version: 1, updated_at: '2026-09-06T01:00:00Z',
}
const schedule: ScanSchedule = {
  data_source_id: 'source-1', enabled: false, frequency: 'daily', timezone: 'Asia/Shanghai',
  local_time: '03:30:00', day_of_week: null, next_run_at: null, last_enqueued_at: null,
  version: 1, updated_at: '2026-09-06T01:00:00Z',
}

function readResponse(path: string) {
  if (path.endsWith('/jobs')) return [job]
  if (path.endsWith('/snapshots')) return [snapshot]
  if (path.includes('/catalog?')) return catalog
  if (path.endsWith('/sampling-policy')) return policy
  if (path.endsWith('/schedule')) return schedule
  return source
}

const auth: AuthContextValue = {
  status: 'authenticated', workspace: { id: 'workspace-1', name: '演示空间', slug: 'demo', role: 'data_admin' },
  user: { id: 'user-1', email: 'admin@example.com', display_name: '管理员', is_active: true, workspaces: [] },
  login: vi.fn(), bootstrap: vi.fn(), acceptInvitation: vi.fn(), logout: vi.fn(), selectWorkspace: vi.fn(),
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><AuthContext.Provider value={auth}><MemoryRouter initialEntries={['/app/data/source-1']}><Routes><Route path="/app/data/:dataSourceId" element={<DataSourceDetailPage />} /></Routes></MemoryRouter></AuthContext.Provider></QueryClientProvider>)
}

test('shows source overview, task history and published snapshot', async () => {
  vi.spyOn(apiClient, 'request').mockImplementation((path) => {
    return Promise.resolve(readResponse(path))
  })
  renderPage()
  expect(await screen.findByRole('heading', { name: '生产库' })).toBeInTheDocument()
  expect(screen.getByText('元数据扫描')).toBeInTheDocument()
  expect(screen.getAllByText('目录 v1').length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText('12 个字段')).toBeInTheDocument()
})

test('starts a metadata scan with a normalized schema allowlist', async () => {
  const request = vi.spyOn(apiClient, 'request').mockImplementation((path, init) => {
    if (init?.method === 'POST') return Promise.resolve({ ...job, id: 'job-2', status: 'queued', progress: 0 })
    return Promise.resolve(readResponse(path))
  })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '扫描数据库结构' }))
  fireEvent.change(screen.getByLabelText('Schema范围'), { target: { value: ' public, reporting ' } })
  fireEvent.click(screen.getByRole('button', { name: '开始扫描' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/v1/workspaces/workspace-1/data-sources/source-1/scans', expect.objectContaining({ method: 'POST', body: JSON.stringify({ schemas: ['public', 'reporting'] }) })))
})
