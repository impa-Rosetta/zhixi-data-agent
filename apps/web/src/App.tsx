import { useEffect, useState } from 'react'

type Health = {
  status: string
  service: string
  version: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${apiBaseUrl}/health`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return (await response.json()) as Health
      })
      .then(setHealth)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : '未知错误')
      })
    return () => controller.abort()
  }, [])

  return (
    <main className="shell">
      <section>
        <p className="eyebrow">A07 企业数据底座智能问析 Agent</p>
        <h1>智析 Data Agent</h1>
        <p className="subtitle">可信、可验证、可私有化部署的企业数据智能分析平台。</p>
      </section>
      <section className="status" aria-live="polite">
        <span className={`indicator ${health?.status === 'ok' ? 'ok' : ''}`} />
        {health ? `API ${health.version} 已连接` : error ? `API连接失败：${error}` : '正在检查服务状态…'}
      </section>
    </main>
  )
}

