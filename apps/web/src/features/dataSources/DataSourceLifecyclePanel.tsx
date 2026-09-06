import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../../lib/api/client'
import type { DataSource, DataSourceUpdateInput, TlsMode } from '../../lib/api/types'
import { useDeleteDataSource, useSetDataSourceState, useTestConnection, useUpdateDataSource } from './api'

type Props = { workspaceId: string; source: DataSource }
type ConfirmAction = 'disable' | 'delete' | null

function messageFor(error: unknown) {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : '操作失败，请刷新后重试。'
}

export function DataSourceLifecyclePanel({ workspaceId, source }: Props) {
  const navigate = useNavigate()
  const update = useUpdateDataSource(workspaceId, source.id)
  const stateChange = useSetDataSourceState(workspaceId, source.id)
  const testConnection = useTestConnection(workspaceId)
  const remove = useDeleteDataSource(workspaceId, source.id)
  const [editOpen, setEditOpen] = useState(false)
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
  const [confirmation, setConfirmation] = useState('')
  const [name, setName] = useState(source.name)
  const [description, setDescription] = useState(source.description ?? '')
  const [host, setHost] = useState(source.host)
  const [port, setPort] = useState(source.port)
  const [databaseName, setDatabaseName] = useState(source.database_name)
  const [tlsMode, setTlsMode] = useState<TlsMode>(source.tls_mode)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [caCertificate, setCaCertificate] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const busy = update.isPending || stateChange.isPending || testConnection.isPending || remove.isPending
  const operationError = update.error ?? stateChange.error ?? testConnection.error ?? remove.error

  function closeEdit() {
    setPassword(''); setUsername(''); setCaCertificate(''); setLocalError(null); setEditOpen(false)
  }

  async function save() {
    setLocalError(null); setSuccess(null)
    const trimmedName = name.trim(); const trimmedHost = host.trim(); const trimmedDatabase = databaseName.trim()
    if (!trimmedName || !trimmedHost || !trimmedDatabase || port < 1 || port > 65535) { setLocalError('请完整填写有效的名称、地址、端口和数据库名。'); return }
    const credentialTouched = Boolean(username || password || caCertificate)
    if (credentialTouched && (!username.trim() || !password)) { setLocalError('轮换凭据时必须同时填写账号和密码。'); return }
    if (tlsMode !== source.tls_mode && (tlsMode === 'verify_ca' || tlsMode === 'verify_full') && !caCertificate.trim()) { setLocalError('切换到证书校验模式时必须同时轮换凭据并提供CA证书。'); return }
    const input: DataSourceUpdateInput = { version: source.version }
    if (trimmedName !== source.name) input.name = trimmedName
    const nextDescription = description.trim() || null
    if (nextDescription !== source.description) input.description = nextDescription
    if (trimmedHost !== source.host) input.host = trimmedHost
    if (port !== source.port) input.port = port
    if (trimmedDatabase !== source.database_name) input.database_name = trimmedDatabase
    if (tlsMode !== source.tls_mode) input.tls_mode = tlsMode
    if (credentialTouched) input.credentials = { username: username.trim(), password, tls_ca_certificate: caCertificate.trim() || null }
    if (Object.keys(input).length === 1) { closeEdit(); return }
    try {
      await update.mutateAsync(input)
      setPassword(''); setUsername(''); setCaCertificate(''); setSuccess('数据源配置已更新。连接相关变更正在重新检测。'); setEditOpen(false)
    } catch { setPassword('') }
  }

  async function retest() {
    setSuccess(null)
    try { await testConnection.mutateAsync(source.id); setSuccess('连接检测任务已创建，可在任务列表查看进度。') } catch { /* Mutation error is rendered below. */ }
  }

  async function enable() {
    setSuccess(null)
    try { await stateChange.mutateAsync({ action: 'enable', version: source.version }); setSuccess('数据源已启用，连接检测任务已创建。') } catch { /* Mutation error is rendered below. */ }
  }

  async function confirm() {
    if (!confirmAction) return
    setSuccess(null)
    try {
      if (confirmAction === 'disable') { await stateChange.mutateAsync({ action: 'disable', version: source.version }); setSuccess('数据源已停用，排队任务已取消。'); setConfirmAction(null) }
      else { await remove.mutateAsync(source.version); void navigate('/app/data', { replace: true }) }
    } catch { /* Mutation error is rendered below. */ }
  }

  return <section className="detail-section lifecycle-section">
    <div className="section-heading"><div><p className="eyebrow">连接治理</p><h2>数据源生命周期</h2></div><span>配置版本 v{source.version}</span></div>
    <div className="lifecycle-card"><div><strong>安全配置与状态操作</strong><p>连接字段变更会自动重新检测；凭据只允许覆盖更新，不会回显。</p></div><div className="lifecycle-actions"><button className="secondary-button" onClick={() => setEditOpen(true)}>编辑配置</button><button className="secondary-button" disabled={busy || source.status === 'disabled'} onClick={() => void retest()}>重新检测</button>{source.status === 'disabled' ? <button className="primary-button" disabled={busy} onClick={() => void enable()}>启用数据源</button> : <button className="secondary-button warning" disabled={busy} onClick={() => setConfirmAction('disable')}>停用数据源</button>}<button className="text-button danger" disabled={busy} onClick={() => { setConfirmation(''); setConfirmAction('delete') }}>删除数据源</button></div></div>
    {success && <div className="alert success" role="status">{success}</div>}
    {operationError && <div className="alert error" role="alert">{messageFor(operationError)}</div>}

    {editOpen && <div className="modal-backdrop" role="presentation"><section className="lifecycle-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-source-title"><header><div><p className="eyebrow">乐观锁版本 v{source.version}</p><h2 id="edit-source-title">编辑数据源配置</h2></div><button className="icon-button" aria-label="关闭" onClick={closeEdit}>×</button></header><div className="lifecycle-dialog-body">
      <div className="form-grid"><label className="field"><span>数据源名称</span><input aria-label="数据源名称" value={name} onChange={(e) => setName(e.target.value)} /></label><label className="field"><span>端口</span><input aria-label="端口" type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} /></label></div>
      <label className="field"><span>用途说明</span><textarea aria-label="用途说明" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      <div className="form-grid"><label className="field"><span>主机名</span><input aria-label="主机名" value={host} onChange={(e) => setHost(e.target.value)} /></label><label className="field"><span>数据库名</span><input aria-label="数据库名" value={databaseName} onChange={(e) => setDatabaseName(e.target.value)} /></label></div>
      <label className="field"><span>TLS策略</span><select aria-label="TLS策略" value={tlsMode} onChange={(e) => setTlsMode(e.target.value as TlsMode)}><option value="require">要求加密</option><option value="verify_full">校验证书与主机</option><option value="verify_ca">校验证书</option><option value="prefer">优先加密</option><option value="disable">关闭（仅限受控内网）</option></select></label>
      <fieldset className="credential-rotation"><legend>轮换只读凭据（可选）</legend><p>留空表示保留现有密文；开始填写后账号与密码必须成套提交。</p><div className="form-grid"><label className="field"><span>新账号</span><input aria-label="新账号" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} /></label><label className="field"><span>新密码</span><input aria-label="新密码" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label></div>{(tlsMode === 'verify_ca' || tlsMode === 'verify_full') && <label className="field"><span>新CA证书（PEM）</span><textarea aria-label="新CA证书" rows={3} value={caCertificate} onChange={(e) => setCaCertificate(e.target.value)} /></label>}</fieldset>
      {tlsMode === 'disable' && <div className="security-warning">关闭TLS只适用于经过批准的隔离内网。</div>}{localError && <div className="alert error" role="alert">{localError}</div>}
    </div><footer><button className="secondary-button" onClick={closeEdit}>取消</button><button className="primary-button" disabled={busy} onClick={() => void save()}>保存配置</button></footer></section></div>}

    {confirmAction && <div className="modal-backdrop" role="presentation"><section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-action-title"><p className="eyebrow">高风险操作确认</p><h2 id="confirm-action-title">{confirmAction === 'delete' ? '删除数据源' : '停用数据源'}</h2><p>{confirmAction === 'delete' ? '删除后连接密文会被销毁且不可恢复。请输入数据源名称确认。' : '停用后新任务不会执行，仍在排队的任务会被取消。'}</p>{confirmAction === 'delete' && <label className="field"><span>输入“{source.name}”</span><input aria-label="删除确认名称" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></label>}<footer><button className="secondary-button" onClick={() => setConfirmAction(null)}>取消</button><button className="danger-button" disabled={busy || (confirmAction === 'delete' && confirmation !== source.name)} onClick={() => void confirm()}>{confirmAction === 'delete' ? '确认删除并销毁凭据' : '确认停用'}</button></footer></section></div>}
  </section>
}
