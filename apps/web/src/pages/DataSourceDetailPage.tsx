import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useAuth } from '../features/auth/context'
import { CatalogBrowser } from '../features/catalog/CatalogBrowser'
import { CatalogDiffPanel } from '../features/catalog/CatalogDiffPanel'
import { CatalogProfilePanel } from '../features/catalog/CatalogProfilePanel'
import { useCancelScanJob, useCatalogSnapshots, useDataSourceDetail, useDataSourceJobs, useMetadataScan, useRetryScanJob } from '../features/dataSources/api'
import { ApiError } from '../lib/api/client'
import type { ScanJob, ScanJobStatus, ScanJobType } from '../lib/api/types'

const jobTypeLabel: Record<ScanJobType, string> = { connection_test: '连接检测', metadata_scan: '元数据扫描', profile_scan: '字段画像' }
const jobStatusLabel: Record<ScanJobStatus, string> = { queued: '等待执行', running: '执行中', succeeded: '已成功', failed: '失败', cancelled: '已取消' }

function formatTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : null
}

function count(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function normalizeSchemas(value: string) {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

function JobRow({ job, onCancel, onRetry, busy }: { job: ScanJob; onCancel: (id: string) => void; onRetry: (id: string) => void; busy: boolean }) {
  const active = job.status === 'queued' || job.status === 'running'
  const retryable = job.status === 'failed' || job.status === 'cancelled'
  return <tr><td><strong>{jobTypeLabel[job.job_type]}</strong><small>{job.trigger === 'scheduled' ? '定时触发' : job.trigger === 'initial' ? '首次接入' : '手动触发'}</small></td><td><span className={`job-status-chip ${job.status}`}>{jobStatusLabel[job.status]}</span></td><td><div className="inline-progress"><span style={{ width: `${job.progress}%` }} /></div><small>{job.progress}% · {job.phase || '等待阶段信息'}</small></td><td>{formatTime(job.created_at)}</td><td>{job.error_code || '—'}</td><td>{active && <button className="text-button danger" disabled={busy} onClick={() => onCancel(job.id)}>取消</button>}{retryable && <button className="text-button" disabled={busy} onClick={() => onRetry(job.id)}>重试</button>}</td></tr>
}

export function DataSourceDetailPage() {
  const { dataSourceId } = useParams()
  const { workspace } = useAuth()
  const [scanOpen, setScanOpen] = useState(false)
  const [schemaInput, setSchemaInput] = useState('')
  const [schemaError, setSchemaError] = useState<string | null>(null)
  const canManage = workspace?.role === 'system_admin' || workspace?.role === 'workspace_admin' || workspace?.role === 'data_admin'
  const source = useDataSourceDetail(canManage ? workspace?.id : undefined, dataSourceId)
  const jobs = useDataSourceJobs(canManage ? workspace?.id : undefined, dataSourceId)
  const snapshots = useCatalogSnapshots(canManage ? workspace?.id : undefined, dataSourceId)
  const scan = useMetadataScan(workspace?.id, dataSourceId)
  const cancel = useCancelScanJob(workspace?.id, dataSourceId)
  const retry = useRetryScanJob(workspace?.id, dataSourceId)
  const wasActive = useRef(false)
  const refreshSource = source.refetch
  const refreshSnapshots = snapshots.refetch
  const hasActiveJob = jobs.data?.some((job) => job.status === 'queued' || job.status === 'running') ?? false

  useEffect(() => {
    if (wasActive.current && !hasActiveJob) {
      void refreshSource()
      void refreshSnapshots()
    }
    wasActive.current = hasActiveJob
  }, [hasActiveJob, refreshSnapshots, refreshSource])

  if (!canManage) return <div className="page"><Link className="back-link" to="/app/data">← 返回数据源</Link><div className="permission-panel"><strong>当前角色无权查看连接详情</strong><p>连接配置只对系统管理员、空间管理员和数据管理员开放。</p></div></div>

  const latestSnapshot = snapshots.data?.[0]
  const actionError = errorMessage(scan.error) ?? errorMessage(cancel.error) ?? errorMessage(retry.error)
  const loadError = errorMessage(source.error) ?? errorMessage(jobs.error) ?? errorMessage(snapshots.error)

  async function startScan() {
    const schemas = normalizeSchemas(schemaInput)
    const invalid = schemas.find((item) => item === 'information_schema' || item.startsWith('pg_') || item.length > 128)
    if (invalid) {
      setSchemaError(`Schema“${invalid}”不允许扫描。`)
      return
    }
    setSchemaError(null)
    try {
      await scan.mutateAsync(schemas)
      setScanOpen(false)
      setSchemaInput('')
    } catch {
      // Mutation state renders the structured error.
    }
  }

  async function cancelJob(jobId: string) {
    try { await cancel.mutateAsync(jobId) } catch { /* Rendered from mutation state. */ }
  }

  async function retryJob(jobId: string) {
    try { await retry.mutateAsync(jobId) } catch { /* Rendered from mutation state. */ }
  }

  return <div className="page detail-page">
    <Link className="back-link" to="/app/data">← 返回数据源</Link>
    {source.isPending && <section className="data-loading"><span className="spinner" />正在读取数据源详情…</section>}
    {loadError && <div className="alert error" role="alert">{loadError}</div>}
    {source.data && <>
      <div className="detail-hero"><div className={`database-mark ${source.data.source_type}`}>{source.data.source_type === 'postgresql' ? 'PG' : 'MY'}</div><div><p className="eyebrow">数据源详情</p><h1>{source.data.name}</h1><p>{source.data.description || '未填写用途说明'}</p></div><span className={`source-status ${source.data.status}`}><i />{source.data.status === 'ready' ? '可用' : source.data.status}</span><button className="primary-button" disabled={source.data.status !== 'ready' || hasActiveJob} onClick={() => setScanOpen(true)}>{hasActiveJob ? '任务执行中…' : '扫描数据库结构'}</button></div>
      <section className="detail-metrics"><article><span>连接地址</span><strong>{source.data.host}:{source.data.port}</strong><small>{source.data.database_name}</small></article><article><span>TLS策略</span><strong>{source.data.tls_mode}</strong><small>配置版本 v{source.data.version}</small></article><article><span>最近成功</span><strong>{formatTime(source.data.last_success_at)}</strong><small>{source.data.health_code || '健康检查通过'}</small></article><article><span>当前目录</span><strong>{source.data.active_snapshot_id ? `v${latestSnapshot?.version ?? '—'}` : '尚未扫描'}</strong><small>{latestSnapshot?.database_product || '等待元数据发布'}</small></article></section>

      <section className="detail-section"><div className="section-heading"><div><p className="eyebrow">版本化目录</p><h2>目录版本</h2></div><span>{snapshots.data?.length ?? 0} 个快照</span></div>{latestSnapshot ? <div className="snapshot-card"><div><span className="snapshot-version">目录 v{latestSnapshot.version}</span><strong>{latestSnapshot.database_product} {latestSnapshot.database_version}</strong><small>{formatTime(latestSnapshot.completed_at)}</small></div><dl><div><dt>Schema</dt><dd>{count(latestSnapshot.object_counts.schemas)} 个</dd></div><div><dt>关系</dt><dd>{count(latestSnapshot.object_counts.relations)} 个</dd></div><div><dt>字段</dt><dd>{count(latestSnapshot.object_counts.columns)} 个字段</dd></div><div><dt>画像</dt><dd>{latestSnapshot.profiling_status}</dd></div></dl></div> : <div className="section-empty">尚无已发布目录。点击“扫描数据库结构”创建第一个不可变快照。</div>}</section>

      {snapshots.data && snapshots.data.length > 0 && workspace && dataSourceId && <CatalogBrowser workspaceId={workspace.id} dataSourceId={dataSourceId} snapshots={snapshots.data} />}
      {snapshots.data && snapshots.data.length > 0 && workspace && dataSourceId && <CatalogProfilePanel workspaceId={workspace.id} dataSourceId={dataSourceId} snapshots={snapshots.data} />}
      {snapshots.data && snapshots.data.length > 0 && workspace && dataSourceId && <CatalogDiffPanel workspaceId={workspace.id} dataSourceId={dataSourceId} snapshots={snapshots.data} />}

      <section className="detail-section"><div className="section-heading"><div><p className="eyebrow">异步执行记录</p><h2>扫描任务</h2></div><span>{jobs.data?.length ?? 0} 条记录</span></div>{actionError && <div className="alert error" role="alert">{actionError}</div>}<div className="table-card"><table className="jobs-table"><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>创建时间</th><th>错误码</th><th>操作</th></tr></thead><tbody>{jobs.data?.map((job) => <JobRow key={job.id} job={job} busy={cancel.isPending || retry.isPending} onCancel={(id) => void cancelJob(id)} onRetry={(id) => void retryJob(id)} />)}</tbody></table>{jobs.data?.length === 0 && <p className="empty-state">暂无任务记录。</p>}</div></section>
    </>}

    {scanOpen && <div className="modal-backdrop" role="presentation"><section className="scan-dialog" role="dialog" aria-modal="true" aria-labelledby="scan-title"><header><div><p className="eyebrow">只读元数据任务</p><h2 id="scan-title">扫描数据库结构</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setScanOpen(false)}>×</button></header><div className="scan-dialog-body"><label className="field"><span>Schema范围</span><textarea rows={4} value={schemaInput} onChange={(event) => setSchemaInput(event.target.value)} placeholder="留空使用安全默认范围；多个Schema用逗号或换行分隔" /></label><p>系统只读取表、视图、字段、约束、索引与注释，不执行用户SQL，不修改业务数据。</p>{schemaError && <div className="alert error" role="alert">{schemaError}</div>}</div><footer><button className="secondary-button" onClick={() => setScanOpen(false)}>取消</button><button className="primary-button" disabled={scan.isPending} onClick={() => void startScan()}>{scan.isPending ? '正在创建任务…' : '开始扫描'}</button></footer></section></div>}
  </div>
}
