import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

import { App } from './App'
import { AuthContext, type AuthContextValue } from './features/auth/context'

const anonymousContext: AuthContextValue = {
  status: 'anonymous',
  user: null,
  workspace: null,
  login: vi.fn(),
  bootstrap: vi.fn(),
  acceptInvitation: vi.fn(),
  logout: vi.fn(),
  selectWorkspace: vi.fn(),
}

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={anonymousContext}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

test('renders the login experience', () => {
  renderRoute('/login')

  expect(screen.getByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
})

test('redirects anonymous users away from the protected workspace', () => {
  renderRoute('/app')

  expect(screen.getByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
})
