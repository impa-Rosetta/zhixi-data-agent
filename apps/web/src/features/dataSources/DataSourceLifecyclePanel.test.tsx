import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import type { DataSource } from '../../lib/api/types'
import { DataSourceLifecyclePanel } from './DataSourceLifecyclePanel'

const source: DataSource = { id: 'source-1', workspace_id: 'workspace-1', name: '生产库', description: '制造数据', source_type: 'postgresql', host: 'db.internal', port: 5432, database_name: 'factory', tls_mode: 'require', network_policy_id: null, status: 'ready', health_code: null, active_snapshot_id: null, version: 4, last_checked_at: null, last_success_at: null, created_at: '2026-09-06T00:00:00Z', updated_at: '2026-09-06T00:00:00Z' }

function renderPanel(value = source) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<MemoryRouter><QueryClientProvider client={client}><DataSourceLifecyclePanel workspaceId="workspace-1" source={value} /></QueryClientProvider></MemoryRouter>)
}

test('patches only changed non-secret fields', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue({ ...source, name: '质量生产库', version: 5 })
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: '编辑配置' }))
  fireEvent.change(screen.getByLabelText('数据源名称'), { target: { value: '质量生产库' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/v1/workspaces/workspace-1/data-sources/source-1', { method: 'PATCH', body: JSON.stringify({ version: 4, name: '质量生产库' }) }))
})

test('requires a second confirmation before disabling', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue({ ...source, status: 'disabled', version: 5 })
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: '停用数据源' }))
  expect(screen.getByRole('heading', { name: '停用数据源' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '确认停用' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/v1/workspaces/workspace-1/data-sources/source-1/disable', { method: 'POST', body: JSON.stringify({ version: 4 }) }))
})

test('requires the exact source name before deletion', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue(undefined)
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: '删除数据源' }))
  const remove = screen.getByRole('button', { name: '确认删除并销毁凭据' })
  expect(remove).toBeDisabled()
  fireEvent.change(screen.getByLabelText('删除确认名称'), { target: { value: '生产库' } })
  fireEvent.click(remove)
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/v1/workspaces/workspace-1/data-sources/source-1?version=4', { method: 'DELETE' }))
})
