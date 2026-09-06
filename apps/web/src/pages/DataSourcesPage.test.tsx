import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../features/auth/context'
import { apiClient } from '../lib/api/client'
import type { WorkspaceRole } from '../lib/api/types'
import { DataSourcesPage } from './DataSourcesPage'

function auth(role: WorkspaceRole): AuthContextValue {
  const workspace = { id: 'workspace-1', name: '演示空间', slug: 'demo', role }
  return {
    status: 'authenticated', workspace,
    user: { id: 'user-1', email: 'admin@example.com', display_name: '管理员', is_active: true, workspaces: [workspace] },
    login: vi.fn(), bootstrap: vi.fn(), acceptInvitation: vi.fn(), logout: vi.fn(), selectWorkspace: vi.fn(),
  }
}

function renderPage(role: WorkspaceRole) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><AuthContext.Provider value={auth(role)}><DataSourcesPage /></AuthContext.Provider></QueryClientProvider>)
}

test('shows a product empty state when an administrator has no sources', async () => {
  vi.spyOn(apiClient, 'request').mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
  renderPage('data_admin')
  expect(await screen.findByRole('heading', { name: '建立第一条可信数据连接' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '添加第一个数据源' })).toBeInTheDocument()
})

test('does not request connection details for an analyst', () => {
  const request = vi.spyOn(apiClient, 'request')
  renderPage('analyst')
  expect(screen.getByText('当前角色没有数据源管理权限，请联系空间管理员。')).toBeInTheDocument()
  expect(request).not.toHaveBeenCalled()
})
