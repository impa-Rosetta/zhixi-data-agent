import type { ReactNode } from 'react'

export function AuthLayout({ eyebrow, title, subtitle, children }: {
  eyebrow: string
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <main className="auth-shell">
      <section className="auth-brand">
        <div className="brand-mark">智</div>
        <p className="eyebrow">A07 企业数据底座智能问析 Agent</p>
        <h1>让每个业务问题<br />都有可信答案。</h1>
        <p>受控规划、可信工具和证据验证，共同构成可私有化部署的企业智能分析平台。</p>
      </section>
      <section className="auth-panel">
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p className="muted">{subtitle}</p>
        {children}
      </section>
    </main>
  )
}
