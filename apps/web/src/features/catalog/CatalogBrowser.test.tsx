import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import type { Catalog, CatalogSnapshot } from '../../lib/api/types'
import { CatalogBrowser } from './CatalogBrowser'

const snapshot = (id: string, version: number): CatalogSnapshot => ({
  id, data_source_id: 'source-1', version, status: 'published', database_product: 'PostgreSQL',
  database_version: '16.4', scan_options: {}, object_counts: { schemas: 1, relations: 2, columns: 5 },
  content_digest: 'abc', sampling_enabled: false, profiling_status: 'disabled', profiling_error_code: null,
  profiling_options: {}, profile_counts: {}, profiling_started_at: null, profiling_finished_at: null,
  started_at: '2026-09-06T00:00:00Z', completed_at: '2026-09-06T00:00:03Z',
})

const current = snapshot('snapshot-2', 2)
const previous = snapshot('snapshot-1', 1)
const catalog: Catalog = {
  snapshot: current,
  schemas: [{
    name: 'public',
    comment: '业务域',
    relations: [{
      name: 'customers', relation_type: 'table', comment: '客户主数据',
      columns: [
        { name: 'id', ordinal_position: 1, data_type: 'integer', native_type: 'int4', nullable: false, default_expression: null, comment: '主键' },
        { name: 'email', ordinal_position: 2, data_type: 'string', native_type: 'varchar(255)', nullable: false, default_expression: null, comment: '联系邮箱' },
        { name: 'created_at', ordinal_position: 3, data_type: 'datetime', native_type: 'timestamp', nullable: false, default_expression: 'now()', comment: null },
      ],
      constraints: [{ name: 'customers_pkey', constraint_type: 'primary_key', columns: ['id'], referenced_schema: null, referenced_relation: null, referenced_columns: [] }],
      indexes: [{ name: 'customers_email_idx', columns: ['email'], unique: true, method: 'btree', predicate: null }],
    }, {
      name: 'orders', relation_type: 'view', comment: null,
      columns: [
        { name: 'id', ordinal_position: 1, data_type: 'integer', native_type: 'int4', nullable: true, default_expression: null, comment: null },
        { name: 'customer_id', ordinal_position: 2, data_type: 'integer', native_type: 'int4', nullable: true, default_expression: null, comment: null },
      ],
      constraints: [], indexes: [],
    }],
  }],
}

function renderBrowser() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><CatalogBrowser workspaceId="workspace-1" dataSourceId="source-1" snapshots={[current, previous]} /></QueryClientProvider>)
}

test('browses schemas, relations and technical details', async () => {
  vi.spyOn(apiClient, 'request').mockResolvedValue(catalog)
  renderBrowser()

  expect(await screen.findByRole('heading', { name: 'customers' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /customers.*3 个字段/ })).toBeInTheDocument()
  expect(screen.getByText('varchar(255)')).toBeInTheDocument()
  expect(screen.getByText('customers_pkey')).toBeInTheDocument()
  expect(screen.getByText('customers_email_idx')).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('搜索目录'), { target: { value: 'orders' } })
  expect(screen.queryByRole('button', { name: /customers/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /orders.*2 个字段/ }))
  expect(screen.getByRole('heading', { name: 'orders' })).toBeInTheDocument()
})

test('loads an immutable historical snapshot on version change', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue(catalog)
  renderBrowser()
  await screen.findByRole('heading', { name: 'customers' })

  fireEvent.change(screen.getByLabelText('目录版本'), { target: { value: previous.id } })

  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/v1/workspaces/workspace-1/data-sources/source-1/catalog?snapshot_id=snapshot-1',
  ))
  expect(within(screen.getByLabelText('目录版本')).getByRole('option', { name: '目录 v1' })).toBeInTheDocument()
})
