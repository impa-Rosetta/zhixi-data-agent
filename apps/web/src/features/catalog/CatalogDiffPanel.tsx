import { useState } from 'react'

import type { CatalogDiff, CatalogSnapshot } from '../../lib/api/types'
import { useCatalogDiffs } from '../dataSources/api'

type Props = {
  workspaceId: string
  dataSourceId: string
  snapshots: CatalogSnapshot[]
}

const changeLabels: Record<string, string> = { added: '新增', removed: '删除', changed: '修改' }
const severityLabels: Record<string, string> = { info: '提示', warning: '警告', breaking: '破坏性' }
const objectLabels: Record<string, string> = {
  schema: 'Schema',
  relation: '表或视图',
  column: '字段',
  constraint: '约束',
  index: '索引',
  scan_scope: '扫描范围',
}
const pageSize = 50

function formatValue(value: Record<string, unknown> | null) {
  return value ? JSON.stringify(value, null, 2) : '无'
}

function DiffItem({ item }: { item: CatalogDiff }) {
  return <details className="diff-item">
    <summary>
      <span className={'diff-change ' + item.change_type}>{changeLabels[item.change_type] ?? item.change_type}</span>
      <code>{item.object_key}</code>
      <span className="diff-object">{objectLabels[item.object_type] ?? item.object_type}</span>
      <span className={'diff-severity ' + item.severity}>{severityLabels[item.severity] ?? item.severity}</span>
    </summary>
    <div className="diff-values">
      <section><h4>变更前</h4><pre>{formatValue(item.before_value)}</pre></section>
      <section><h4>变更后</h4><pre>{formatValue(item.after_value)}</pre></section>
    </div>
  </details>
}

export function CatalogDiffPanel({ workspaceId, dataSourceId, snapshots }: Props) {
  const [snapshotId, setSnapshotId] = useState(snapshots[0]?.id)
  const [offset, setOffset] = useState(0)
  const [changeType, setChangeType] = useState('all')
  const [severity, setSeverity] = useState('all')
  const [objectType, setObjectType] = useState('all')
  const diffs = useCatalogDiffs(workspaceId, dataSourceId, snapshotId, offset, pageSize)
  const items = (diffs.data?.items ?? []).filter((item) =>
    (changeType === 'all' || item.change_type === changeType) &&
    (severity === 'all' || item.severity === severity) &&
    (objectType === 'all' || item.object_type === objectType)
  )
  const total = diffs.data?.total ?? 0
  const currentSnapshot = snapshots.find((snapshot) => snapshot.id === snapshotId)
  const previousSnapshot = currentSnapshot ? snapshots.find((snapshot) => snapshot.version === currentSnapshot.version - 1) : undefined
  const hasPreviousPage = offset > 0
  const hasNextPage = offset + pageSize < total

  return <section className="detail-section diff-section">
    <div className="section-heading"><div><p className="eyebrow">确定性版本比较</p><h2>结构变化</h2></div><label className="snapshot-picker"><span>比较版本</span><select aria-label="比较版本" value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setOffset(0) }}>{snapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>目录 v{snapshot.version}</option>)}</select></label></div>
    <div className="diff-card">
      <header className="diff-summary"><div><strong>{total} 项变化</strong><span>{previousSnapshot ? '目录 v' + previousSnapshot.version + ' → v' + currentSnapshot?.version : '首个目录版本'}</span></div><span>当前筛选 {items.length} 项</span></header>
      <div className="diff-filters">
        <label><span>变化类型</span><select aria-label="变化类型" value={changeType} onChange={(event) => setChangeType(event.target.value)}><option value="all">全部</option><option value="added">新增</option><option value="removed">删除</option><option value="changed">修改</option></select></label>
        <label><span>影响级别</span><select aria-label="影响级别" value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="all">全部</option><option value="breaking">破坏性</option><option value="warning">警告</option><option value="info">提示</option></select></label>
        <label><span>对象类型</span><select aria-label="对象类型" value={objectType} onChange={(event) => setObjectType(event.target.value)}><option value="all">全部</option><option value="schema">Schema</option><option value="relation">表或视图</option><option value="column">字段</option><option value="constraint">约束</option><option value="index">索引</option></select></label>
      </div>
      {diffs.isPending && <div className="catalog-state"><span className="spinner" />正在读取结构变化…</div>}
      {diffs.isError && <div className="catalog-state error">结构变化读取失败，请稍后重试。</div>}
      {diffs.data && items.length === 0 && <div className="diff-empty">{total === 0 ? '该版本没有结构变化。' : '当前筛选条件下没有变化。'}</div>}
      <div className="diff-list">{items.map((item) => <DiffItem key={item.id} item={item} />)}</div>
      {(hasPreviousPage || hasNextPage) && <footer className="diff-pagination"><button className="secondary-button" disabled={!hasPreviousPage} onClick={() => setOffset(Math.max(0, offset - pageSize))}>上一页</button><span>第 {Math.floor(offset / pageSize) + 1} 页</span><button className="secondary-button" disabled={!hasNextPage} onClick={() => setOffset(offset + pageSize)}>下一页</button></footer>}
    </div>
  </section>
}
