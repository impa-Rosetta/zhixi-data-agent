import { useState } from 'react'

import type { CatalogColumnProfile, CatalogSnapshot } from '../../lib/api/types'
import { useCatalogProfiles } from '../dataSources/api'

type Props = {
  workspaceId: string
  dataSourceId: string
  snapshots: CatalogSnapshot[]
}

const sensitivityLabels: Record<string, string> = {
  email: '邮箱',
  phone: '手机号',
  national_id: '身份证',
  bank_card: '银行卡',
  password: '密码',
  token: '令牌',
}
const statusLabels: Record<string, string> = {
  disabled: '未启用',
  pending: '等待画像',
  running: '画像执行中',
  succeeded: '画像已完成',
  failed: '画像失败',
  cancelled: '画像已取消',
}

function count(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function optional(value: string | number | null, suffix = '') {
  return value === null ? '—' : String(value) + suffix
}

function percent(value: number | null) {
  return value === null ? '—' : (value * 100).toFixed(1) + '%'
}

function ProfileDetail({ item }: { item: CatalogColumnProfile }) {
  const sensitive = Boolean(item.sensitivity_type)
  return <article className="profile-detail">
    <header><div><p className="eyebrow">{item.schema_name}.{item.relation_name}</p><h3>{item.column_name}</h3><p>{item.native_type} · {item.data_type}</p></div>{sensitive ? <span className="sensitive-chip">敏感字段</span> : <span className="safe-chip">允许画像</span>}</header>
    {sensitive && <div className="sensitive-notice"><strong>{sensitivityLabels[item.sensitivity_type ?? ''] ?? item.sensitivity_type}</strong><span>置信度 {(item.sensitivity_confidence * 100).toFixed(0)}%</span><p>敏感字段不保存或展示样例值</p></div>}
    <dl className="profile-metrics">
      <div><dt>估算行数</dt><dd>{optional(item.estimated_row_count)}</dd></div>
      <div><dt>采样行数</dt><dd>{item.sample_row_count}</dd></div>
      <div><dt>样本空值率</dt><dd>{percent(item.sample_null_rate)}</dd></div>
      <div><dt>样本基数</dt><dd>{optional(item.sampled_distinct_count)}</dd></div>
      <div><dt>最小值</dt><dd>{sensitive ? '受保护' : optional(item.minimum_value)}</dd></div>
      <div><dt>最大值</dt><dd>{sensitive ? '受保护' : optional(item.maximum_value)}</dd></div>
      <div><dt>长度范围</dt><dd>{item.minimum_length === null ? '—' : item.minimum_length + '–' + item.maximum_length}</dd></div>
      <div><dt>平均长度</dt><dd>{optional(item.average_length)}</dd></div>
    </dl>
    <section className="profile-samples"><h4>脱敏样例 <span>{item.samples.length}</span></h4>{sensitive ? <p>此字段被确定性敏感识别器拦截，没有持久化样例。</p> : item.samples.length ? <div>{item.samples.map((sample) => <code key={sample.ordinal}>{sample.masked_value}</code>)}</div> : <p>没有可展示的安全样例。</p>}</section>
  </article>
}

export function CatalogProfilePanel({ workspaceId, dataSourceId, snapshots }: Props) {
  const [snapshotId, setSnapshotId] = useState(snapshots[0]?.id)
  const [selectedColumnId, setSelectedColumnId] = useState<string | null>(null)
  const profile = useCatalogProfiles(workspaceId, dataSourceId, snapshotId)
  const items = profile.data?.items ?? []
  const selected = items.find((item) => item.column_id === selectedColumnId) ?? items[0]
  const status = profile.data?.profiling_status

  return <section className="detail-section profile-section">
    <div className="section-heading"><div><p className="eyebrow">受控数据特征</p><h2>字段画像</h2></div><label className="snapshot-picker"><span>画像版本</span><select aria-label="画像版本" value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setSelectedColumnId(null) }}>{snapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>目录 v{snapshot.version}</option>)}</select></label></div>
    <div className="profile-card">
      {profile.isPending && <div className="catalog-state"><span className="spinner" />正在读取字段画像…</div>}
      {profile.isError && <div className="catalog-state error">字段画像读取失败，请稍后重试。</div>}
      {profile.data && status !== 'succeeded' && <div className="profile-status"><span className={'job-status-chip ' + status}>{statusLabels[status ?? ''] ?? status}</span><h3>{status === 'disabled' ? '当前快照未启用安全画像' : '字段画像尚不可用'}</h3><p>{profile.data.profiling_error_code ? '错误码：' + profile.data.profiling_error_code : '可在安全采样策略中授权普通表，下一次扫描将生成受限画像。'}</p></div>}
      {profile.data && status === 'succeeded' && <div className="profile-browser"><aside><header><strong>{items.length} 个字段</strong><span>{count(profile.data.profile_counts.samples)} 个样例</span></header>{items.map((item) => <button key={item.column_id} className={selected?.column_id === item.column_id ? 'active' : ''} aria-label={[item.column_name, item.sensitivity_type ? '敏感字段' : '普通字段'].join(' ')} onClick={() => setSelectedColumnId(item.column_id)}><span><strong>{item.column_name}</strong>{item.sensitivity_type && <i>敏感</i>}</span><small>{item.schema_name}.{item.relation_name}</small></button>)}</aside><div>{selected ? <ProfileDetail item={selected} /> : <div className="catalog-placeholder">本次画像没有字段结果。</div>}</div></div>}
    </div>
  </section>
}
