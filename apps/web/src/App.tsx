import { Navigate, Route, Routes } from 'react-router-dom'

import { LoadingScreen } from './components/feedback/LoadingScreen'
import { AppShell } from './components/layout/AppShell'
import { useAuth } from './features/auth/context'
import { AnalysisHomePage } from './pages/AnalysisHomePage'
import { DataSourceDetailPage } from './pages/DataSourceDetailPage'
import { DataSourcesPage } from './pages/DataSourcesPage'
import { InvitePage } from './pages/InvitePage'
import { LoginPage } from './pages/LoginPage'
import { MembersPage } from './pages/MembersPage'
import { SetupPage } from './pages/SetupPage'
import { SemanticModelsPage } from './pages/SemanticModelsPage'
import { StartPage } from './pages/StartPage'

function ProtectedRoute() {
  const { status } = useAuth()
  if (status === 'loading') return <LoadingScreen label="正在恢复安全会话…" />
  return status === 'authenticated' ? <AppShell /> : <Navigate to="/login" replace />
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<StartPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite" element={<InvitePage />} />
      <Route path="/app" element={<ProtectedRoute />}>
        <Route index element={<AnalysisHomePage />} />
        <Route path="data" element={<DataSourcesPage />} />
        <Route path="data/:dataSourceId" element={<DataSourceDetailPage />} />
        <Route path="semantic" element={<SemanticModelsPage />} />
        <Route path="members" element={<MembersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
