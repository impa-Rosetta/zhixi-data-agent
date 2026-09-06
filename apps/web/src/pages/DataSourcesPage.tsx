import { useEffect, useState } from 'react'

import { DataSourceWizard } from '../features/dataSources/DataSourceWizard'
import { useDataSources, useScanJob, useTestConnection } from '../features/dataSources/api'
import { useAuth } from '../features/auth/context'
import { ApiError } from '../lib/api/client'
import type { DataSource, DataSourceCreateResult, DataSourceStatus, ScanJobStatus } from '../lib/api/types'

const statusLabel: Record<DataSourceStatus, string> = {
  draft: '待检测', testing: '检测中', ready: '可用', degraded: '异常', disabled: '已停用', deleted: '已删除',
}
const jobLabel: Record<ScanJobStatus, string> = {
  queued: '等待执行', running: '正在检测', succeeded: '连接成功', failed: '连接失败', cancelled: '已取消',
}

function formatTime(value: string | null) {
  if (!value) return '尚未检测'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function sourceIcon(source: DataSource) {
  return source.source_type === 'postgresql' ? 'PG' : 'MY'
}

export function DataSourcesPage() {
  const { workspace } = useAuth()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const canManage = workspace?.role === 'system_admin' || workspace?.role === 'workspace_admin' || workspace?.role === 'data_admin'
  const sources = useDataSources(canManage ? workspace?.id : undefined)
  const refreshSources = sources.refetch
  const testConnection = useTestConnection(workspace?.id)
  const job = useScanJob(workspace?.id, activeJobId)

  useEffect(() => {
    const status = job.data?.status
    if (status === 'succeeded' || status === 'failed' || status === 'cancelled') void refreshSources()
  }, [job.data?.status, refreshSources])

  function created(result: DataSourceCreateResult) {
    setActiveJobId(result.job.id)
    setWizardOpen(false)
  }

  async function retest(dataSourceId: string) {
    const result = await testConnection.mutateAsync(dataSourceId)
    setActiveJobId(result.id)
  }

  const loadError = sources.error instanceof ApiError ? sources.error.message : sources.error?.message
  const actionError = testConnection.error instanceof ApiError ? testConnection.error.message : testConnection.error?.message

  if (!canManage) return <div className="page"><div className="page-heading"><div><p className="eyebrow">企业数据底座</p><h1>数据管理</h1><p>当前角色没有数据源管理权限，请联系空间管理员。</p></div></div><div className="permission-panel"><strong>受权限策略保护</strong><p>分析用户与审计员不会接触连接地址或数据库凭据。</p></div></div>

  return <div className="page data-page">
    <div className="page-heading"><div><p className="eyebrow">企业数据底座</p><h1>数据源</h1><p>安全接入 PostgreSQL 与 MySQL，所有连接均经过网络边界和只读权限校验。</p></div><button className="primary-button" onClick={() => setWizardOpen(true)}>＋ 添加数据源</button></div>

    {activeJobId && job.data && <div className={`job-banner ${job.data.status}`} role="status"><div><span className="status-pulse" /><strong>{jobLabel[job.data.status]}</strong><p>{job.data.status === 'failed' ? `错误代码：${job.data.error_code ?? 'unknown'}` : `连接安全检测进度 ${job.data.progress}%`}</p></div><div className="progress-track" aria-label={`检测进度${job.data.progress}%`}><span style={{ width: `${job.data.progress}%` }} /></div></div>}
    {job.error && <div className="alert error" role="alert">检测状态暂时无法获取，请稍后刷新。</div>}
    {(loadError || actionError) && <div className="alert error" role="alert">{loadError ?? actionError}</div>}

    {sources.isPending && <section className="data-loading" aria-live="polite"><span className="spinner" />正在读取数据源…</section>}
    {!sources.isPending && sources.data?.items.length === 0 && <section className="data-empty"><div className="empty-illustration">DB</div><h2>建立第一条可信数据连接</h2><p>系统只读取授权范围内的结构信息。采样默认关闭，凭据使用信封加密保存。</p><button className="primary-button" onClick={() => setWizardOpen(true)}>添加第一个数据源</button></section>}
    {sources.data && sources.data.items.length > 0 && <section className="source-grid" aria-label="数据源列表">{sources.data.items.map((source) => <article className="source-card" key={source.id}>
      <div className="source-card-head"><span className={`database-mark ${source.source_type}`}>{sourceIcon(source)}</span><div><h2>{source.name}</h2><p>{source.description || '未填写用途说明'}</p></div><span className={`source-status ${source.status}`}><i />{statusLabel[source.status]}</span></div>
      <dl><div><dt>连接地址</dt><dd>{source.host}:{source.port}</dd></div><div><dt>数据库</dt><dd>{source.database_name}</dd></div><div><dt>TLS策略</dt><dd>{source.tls_mode}</dd></div><div><dt>最近成功</dt><dd>{formatTime(source.last_success_at)}</dd></div></dl>
      <footer><span>配置版本 v{source.version}</span><button className="text-button" disabled={testConnection.isPending || source.status === 'testing'} onClick={() => void retest(source.id)}>{source.status === 'testing' ? '检测中…' : '重新检测'}</button></footer>
    </article>)}</section>}

    {wizardOpen && workspace && <DataSourceWizard workspaceId={workspace.id} onClose={() => setWizardOpen(false)} onCreated={created} />}
  </div>
}
