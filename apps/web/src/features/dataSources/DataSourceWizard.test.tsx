import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { apiClient } from '../../lib/api/client'
import type { DataSourceCreateResult } from '../../lib/api/types'
import { DataSourceWizard } from './DataSourceWizard'

const result: DataSourceCreateResult = {
  data_source: {
    id: 'source-1', workspace_id: 'workspace-1', name: '生产库', description: null,
    source_type: 'postgresql', host: 'source-postgres', port: 5432, database_name: 'factory_demo',
    tls_mode: 'disable', network_policy_id: null, status: 'testing', health_code: null,
    active_snapshot_id: null, version: 1, last_checked_at: null, last_success_at: null,
    created_at: '2026-09-06T00:00:00Z', updated_at: '2026-09-06T00:00:00Z',
  },
  job: {
    id: 'job-1', data_source_id: 'source-1', snapshot_id: null, parent_job_id: null,
    retry_of_job_id: null, job_type: 'connection_test', trigger: 'initial', status: 'queued',
    phase: null, progress: 0, error_code: null, created_at: '2026-09-06T00:00:00Z',
    started_at: null, heartbeat_at: null, cancel_requested_at: null, finished_at: null,
  },
}

function renderWizard(onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return {
    onCreated,
    ...render(<QueryClientProvider client={client}><DataSourceWizard workspaceId="workspace-1" onClose={vi.fn()} onCreated={onCreated} /></QueryClientProvider>),
  }
}

test('validates each step before moving forward', async () => {
  renderWizard()
  fireEvent.click(screen.getByRole('button', { name: '下一步' }))
  expect(await screen.findByText('请输入数据源名称')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '添加企业数据源' })).toBeInTheDocument()
})

test('creates a source with an explicit security configuration and clears the secret field', async () => {
  const request = vi.spyOn(apiClient, 'request').mockResolvedValue(result)
  const { onCreated } = renderWizard()

  fireEvent.change(screen.getByLabelText('数据源名称'), { target: { value: '生产库' } })
  fireEvent.click(screen.getByRole('button', { name: '下一步' }))

  fireEvent.change(await screen.findByLabelText('主机名'), { target: { value: 'source-postgres' } })
  fireEvent.change(screen.getByLabelText('数据库名'), { target: { value: 'factory_demo' } })
  fireEvent.change(screen.getByLabelText('只读账号'), { target: { value: 'zhixi_reader' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'reader-local-only' } })
  fireEvent.change(screen.getByLabelText('TLS策略'), { target: { value: 'disable' } })
  fireEvent.click(screen.getByRole('button', { name: '下一步' }))
  fireEvent.click(await screen.findByRole('button', { name: '创建并开始检测' }))

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(result))
  expect(request).toHaveBeenCalledWith('/api/v1/workspaces/workspace-1/data-sources', expect.objectContaining({ method: 'POST' }))
  const submittedBody = request.mock.calls[0]?.[1]?.body
  if (typeof submittedBody !== 'string') throw new Error('expected a JSON request body')
  const requestBody = JSON.parse(submittedBody) as { credentials: { password: string }; tls_mode: string }
  expect(requestBody.credentials.password).toBe('reader-local-only')
  expect(requestBody.tls_mode).toBe('disable')
})
