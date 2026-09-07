import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../../features/auth/context'

const nav = [
  { to: '/app', label: '智能问析', end: true },
  { to: '/app/queries', label: '查询实验室' },
  { to: '/app/history', label: '分析记录', disabled: true },
  { to: '/app/data', label: '数据管理' },
  { to: '/app/semantic', label: '语义模型' },
  { to: '/app/members', label: '成员与权限' },
  { to: '/app/audit', label: '审计日志', disabled: true },
]

export function AppShell() {
  const auth = useAuth(); const navigate = useNavigate()
  return <div className="app-shell">
    <header className="topbar">
      <NavLink to="/app" className="brand"><span className="brand-mark small">智</span><span>智析</span></NavLink>
      <div className="topbar-actions">
        <label className="workspace-picker"><span className="sr-only">当前工作空间</span><select value={auth.workspace?.id ?? ''} onChange={(event) => auth.selectWorkspace(event.target.value)}>{auth.user?.workspaces.map((workspace) => <option value={workspace.id} key={workspace.id}>{workspace.name}</option>)}</select></label>
        <button className="user-button" onClick={() => { void auth.logout().then(() => { void navigate('/login', { replace: true }) }) }}>{auth.user?.display_name}<span>退出</span></button>
      </div>
    </header>
    <aside className="sidebar" aria-label="主导航">
      <nav>{nav.map((item) => item.disabled ? <span className="nav-item disabled" key={item.to}>{item.label}<small>即将开放</small></span> : <NavLink className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} end={item.end} to={item.to} key={item.to}>{item.label}</NavLink>)}</nav>
      <div className="sidebar-footer"><span className="status-dot" />安全服务已连接</div>
    </aside>
    <main className="workspace-content"><Outlet /></main>
  </div>
}
