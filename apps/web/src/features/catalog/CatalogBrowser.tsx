import { useState } from 'react'

import type { CatalogRelation, CatalogSnapshot } from '../../lib/api/types'
import { useCatalog } from '../dataSources/api'

type Props = {
  workspaceId: string
  dataSourceId: string
  snapshots: CatalogSnapshot[]
}

function relationLabel(type: string) {
  return type === 'view' || type === 'materialized_view' ? '视图' : '表'
}

function constraintLabel(type: string) {
  const labels: Record<string, string> = {
    primary_key: '主键',
    foreign_key: '外键',
    unique: '唯一',
    check: '检查',
  }
  return labels[type] ?? type
}

function relationKey(schema: string, relation: string) {
  return schema + '.' + relation
}

function RelationDetails({ schemaName, relation }: { schemaName: string; relation: CatalogRelation }) {
  return <article className="catalog-detail">
    <header>
      <div><p className="eyebrow">{schemaName} · {relationLabel(relation.relation_type)}</p><h3>{relation.name}</h3><p>{relation.comment || '暂无对象注释'}</p></div>
      <span>{relation.columns.length} 个字段</span>
    </header>
    <div className="catalog-subsection">
      <h4>字段</h4>
      <div className="table-card"><table className="catalog-columns"><thead><tr><th>字段</th><th>标准类型</th><th>数据库类型</th><th>可空</th><th>默认值</th><th>注释</th></tr></thead><tbody>{relation.columns.map((column) => <tr key={column.name}><td><strong>{column.name}</strong><small>#{column.ordinal_position}</small></td><td>{column.data_type}</td><td><code>{column.native_type}</code></td><td>{column.nullable ? '是' : '否'}</td><td><code>{column.default_expression || '—'}</code></td><td>{column.comment || '—'}</td></tr>)}</tbody></table></div>
    </div>
    <div className="catalog-technical-grid">
      <section><h4>约束 <span>{relation.constraints.length}</span></h4>{relation.constraints.length ? <ul>{relation.constraints.map((constraint) => <li key={constraint.name}><div><strong>{constraint.name}</strong><small>{constraintLabel(constraint.constraint_type)}</small></div><code>{constraint.columns.join(', ') || '—'}</code>{constraint.referenced_relation && <small>→ {constraint.referenced_schema}.{constraint.referenced_relation} ({constraint.referenced_columns.join(', ')})</small>}</li>)}</ul> : <p>没有约束信息</p>}</section>
      <section><h4>索引 <span>{relation.indexes.length}</span></h4>{relation.indexes.length ? <ul>{relation.indexes.map((index) => <li key={index.name}><div><strong>{index.name}</strong><small>{index.unique ? '唯一索引' : '普通索引'} · {index.method || '默认方法'}</small></div><code>{index.columns.join(', ')}</code>{index.predicate && <small>条件：{index.predicate}</small>}</li>)}</ul> : <p>没有索引信息</p>}</section>
    </div>
  </article>
}

export function CatalogBrowser({ workspaceId, dataSourceId, snapshots }: Props) {
  const [snapshotId, setSnapshotId] = useState(snapshots[0]?.id)
  const [query, setQuery] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const catalog = useCatalog(workspaceId, dataSourceId, snapshotId)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const filteredSchemas = (catalog.data?.schemas ?? []).map((schema) => {
    const schemaMatches = schema.name.toLocaleLowerCase().includes(normalizedQuery)
    return {
      ...schema,
      relations: schema.relations.filter((relation) => schemaMatches || relation.name.toLocaleLowerCase().includes(normalizedQuery)),
    }
  }).filter((schema) => schema.relations.length > 0 || schema.name.toLocaleLowerCase().includes(normalizedQuery))
  const relations = filteredSchemas.flatMap((schema) => schema.relations.map((relation) => ({ schema, relation })))
  const selected = relations.find(({ schema, relation }) => relationKey(schema.name, relation.name) === selectedKey) ?? relations[0]

  return <section className="detail-section catalog-section">
    <div className="section-heading"><div><p className="eyebrow">可追溯元数据</p><h2>目录结构</h2></div><label className="snapshot-picker"><span>目录版本</span><select aria-label="目录版本" value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setSelectedKey(null) }}>{snapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>目录 v{snapshot.version}</option>)}</select></label></div>
    <div className="catalog-browser">
      <aside className="catalog-tree">
        <label className="catalog-search"><span className="sr-only">搜索目录</span><input aria-label="搜索目录" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Schema、表或视图" /></label>
        {catalog.isPending && <div className="catalog-state"><span className="spinner" />正在读取目录…</div>}
        {catalog.isError && <div className="catalog-state error">目录读取失败，请稍后重试。</div>}
        {catalog.data && filteredSchemas.length === 0 && <div className="catalog-state">没有匹配的目录对象。</div>}
        {filteredSchemas.map((schema) => <section className="schema-group" key={schema.name}><header><strong>{schema.name}</strong><span>{schema.relations.length}</span></header>{schema.comment && <p>{schema.comment}</p>}<div>{schema.relations.map((relation) => {
          const key = relationKey(schema.name, relation.name)
          const active = selected && relationKey(selected.schema.name, selected.relation.name) === key
          return <button key={key} className={active ? 'active' : ''} aria-label={[relation.name, relationLabel(relation.relation_type), relation.columns.length, '个字段'].join(' ')} onClick={() => setSelectedKey(key)}><span><i>{relationLabel(relation.relation_type)}</i><strong>{relation.name}</strong></span><small>{relation.columns.length} 个字段</small></button>
        })}</div></section>)}
      </aside>
      <div className="catalog-content">{selected ? <RelationDetails schemaName={selected.schema.name} relation={selected.relation} /> : !catalog.isPending && <div className="catalog-placeholder">选择一个表或视图查看字段、约束和索引。</div>}</div>
    </div>
  </section>
}
