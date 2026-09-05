import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import { LoadingScreen } from '../components/feedback/LoadingScreen'
import { useAuth } from '../features/auth/context'
import { ApiError, apiClient } from '../lib/api/client'

export function StartPage() {
  const { status } = useAuth()
  const [initialized, setInitialized] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiClient.request<{ initialized: boolean }>('/api/v1/auth/bootstrap-status', {}, false)
      .then((result) => setInitialized(result.initialized))
      .catch((reason: unknown) => setError(reason instanceof ApiError ? reason.message : '服务不可用'))
  }, [])

  if (status === 'loading' || (initialized === null && !error)) return <LoadingScreen label="正在检查平台状态…" />
  if (error) return <main className="center-screen"><h1>暂时无法连接智析</h1><p>{error}</p><button onClick={() => window.location.reload()}>重新检查</button></main>
  if (status === 'authenticated') return <Navigate to="/app" replace />
  return <Navigate to={initialized ? '/login' : '/setup'} replace />
}
