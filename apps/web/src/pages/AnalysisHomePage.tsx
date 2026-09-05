import { useAuth } from '../features/auth/context'

export function AnalysisHomePage() {
  const { user, workspace } = useAuth()
  return <div className="page home-page">
    <div className="page-heading"><div><p className="eyebrow">{workspace?.name}</p><h1>企业数据智能问析</h1><p>你好，{user?.display_name}。用自然语言提出业务问题，Agent 将规划并调用可信分析工具。</p></div><span className="role-chip">{roleLabel(workspace?.role)}</span></div>
    <section className="ask-card">
      <label htmlFor="agent-question">想分析什么？</label>
      <textarea id="agent-question" placeholder="例如：本月哪条产线的不良率出现异常？" disabled />
      <div className="ask-footer"><span>Agent执行引擎将在M5启用</span><button disabled>开始分析</button></div>
    </section>
    <section className="readiness-grid">
      <article><span className="status-dot" /><div><strong>身份与权限就绪</strong><p>当前请求受工作空间Policy Engine保护。</p></div></article>
      <article><span className="pending-dot" /><div><strong>等待接入企业数据</strong><p>M2将提供数据源连接与元数据扫描。</p></div></article>
      <article><span className="pending-dot" /><div><strong>等待Agent运行时</strong><p>M5将启用计划、工具执行和答案验证。</p></div></article>
    </section>
  </div>
}

function roleLabel(role?: string): string {
  return ({ system_admin: '系统管理员', workspace_admin: '空间管理员', data_admin: '数据管理员', analyst: '分析用户', auditor: '审计员' } as Record<string, string>)[role ?? ''] ?? '成员'
}
