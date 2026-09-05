import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { apiClient } from '../../lib/api/client'
import type { TokenResponse, User } from '../../lib/api/types'
import { AuthContext, type AuthContextValue } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthContextValue['status']>(() => apiClient.hasRefreshToken() ? 'loading' : 'anonymous')
  const [user, setUser] = useState<User | null>(null)
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)

  const loadUser = useCallback(async (): Promise<void> => {
    const nextUser = await apiClient.request<User>('/api/v1/auth/me')
    setUser(nextUser)
    setWorkspaceId((current) =>
      nextUser.workspaces.some((item) => item.id === current) ? current : (nextUser.workspaces[0]?.id ?? null),
    )
    setStatus('authenticated')
  }, [])

  const establish = useCallback(async (path: string, body: unknown): Promise<void> => {
    const tokens = await apiClient.request<TokenResponse>(path, {
      method: 'POST',
      body: JSON.stringify(body),
    }, false)
    apiClient.setTokens(tokens)
    await loadUser()
  }, [loadUser])

  useEffect(() => {
    const unsubscribe = apiClient.onAuthLost(() => {
      setUser(null)
      setStatus('anonymous')
    })
    if (apiClient.hasRefreshToken()) {
      void apiClient.refresh().then(loadUser).catch(() => setStatus('anonymous'))
    }
    return unsubscribe
  }, [loadUser])

  const value: AuthContextValue = {
    status,
    user,
    workspace: user?.workspaces.find((item) => item.id === workspaceId) ?? null,
    login: (input) => establish('/api/v1/auth/login', input),
    bootstrap: (input) => establish('/api/v1/auth/bootstrap', input),
    acceptInvitation: (input) => establish('/api/v1/auth/accept-invitation', input),
    logout: async () => {
      try {
        await apiClient.logout()
      } finally {
        apiClient.clearTokens()
        setUser(null)
        setStatus('anonymous')
      }
    },
    selectWorkspace: setWorkspaceId,
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
