import { useMemo, useState } from 'react'

import './SemanticModelsPage.css'

import { useAuth } from '../features/auth/context'
import { useCatalogSnapshots, useDataSources } from '../features/dataSources/api'
import { MappingCandidate, SemanticModel, useCreateManufacturingTemplate, useCreateSemanticDraft, useMappingCandidates, usePublishSemanticModel, useSaveSemanticDraft, useSemanticModels } from '../features/semantic/api'

function Formula({ model }: { model: SemanticModel['document']['metrics'][number] }) {
  const formula = model.formula
  const text = formula.type === 'ratio_of_sums'
    ? `SUM(${formula.numerator}) ÷ SUM(${formula.denominator}) × ${formula.scale}`
    : `${formula.type.toUpperCase()}(${formula.attribute ?? '*'})`
  return <code className="formula-code">{text}</code>
}

export function SemanticModelsPage() {
  const { workspace } = useAuth()
  const models = useSemanticModels(workspace?.id)
  const createTemplate = useCreateManufacturingTemplate(workspace?.id)
  const saveDraft = useSaveSemanticDraft(workspace?.id)
  const publish = usePublishSemanticModel(workspace?.id)
  const createDraft = useCreateSemanticDraft(workspace?.id)
  const sources = useDataSources(workspace?.id)
  const [selectedId, setSelectedId] = useState<string>()
  const [sourceId, setSourceId] = useState<string>()
  const [snapshotId, setSnapshotId] = useState<string>()
  const snapshots = useCatalogSnapshots(workspace?.id, sourceId)
  const selected = useMemo(() => models.data?.items.find((item) => item.id === selectedId) ?? models.data?.items[0], [models.data, selectedId])
  const candidates = useMappingCandidates(workspace?.id, selected?.id, snapshotId)
  const [accepted, setAccepted] = useState<Record<string, MappingCandidate>>({})

  async function create() {
    const name = `制造质量模型 ${new Date().toLocaleString('zh-CN', { hour12: false })}`
    const result = await createTemplate.mutateAsync(name)
    setAccepted({})
    setSnapshotId(undefined)
    setSelectedId(result.id)
  }

  async function saveMappings() {
    if (!selected) return
    const next: SemanticModel = { ...selected, document: { ...selected.document, mappings: Object.values(accepted).map((item) => ({ semantic_attribute: item.semantic_attribute, snapshot_id: item.snapshot_id, relation_id: item.relation_id, column_id: item.column_id, confirmed: true, confidence: item.confidence, reason: item.reason })) } }
    await saveDraft.mutateAsync(next)
  }

  return <section className="semantic-page">
    <header className="page-heading semantic-heading">
      <div><span className="eyebrow">M3 · 可信语义层</span><h1>语义模型工作台</h1><p>先固化口径，再让 Agent 选择指标与工具。发布版本不可变，可追溯到目录快照。</p></div>
      <button className="primary-button" onClick={() => void create()} disabled={createTemplate.isPending}>从制造业模板创建</button>
    </header>
    <div className="semantic-layout">
      <aside className="semantic-model-list">
        <div className="section-title"><strong>模型</strong><span>{models.data?.total ?? 0}</span></div>
        {models.isLoading && <p className="muted">正在加载…</p>}
        {models.data?.items.map((model) => <button key={model.id} className={`model-list-item ${selected?.id === model.id ? 'active' : ''}`} onClick={() => { setAccepted({}); setSnapshotId(undefined); setSelectedId(model.id) }}><span>{model.name}</span><small>{model.status === 'published' ? `已发布 v${model.published_version}` : `草稿 · r${model.version}`}</small></button>)}
      </aside>
      <main className="semantic-workbench">
        {!selected ? <div className="empty-state"><h2>建立第一个可信语义模型</h2><p>内置 A07 制造质量模板包含实体、关系、维度和 19 个可复用指标。</p></div> : <>
          <div className="model-summary"><div><div className={`status-pill ${selected.status}`}>{selected.status === 'published' ? '已发布' : '草稿'}</div><h2>{selected.name}</h2><p>{selected.description}</p></div><div className="summary-counts">{Object.entries(selected.counts).slice(0, 5).map(([key, count]) => <span key={key}><strong>{count}</strong>{({ entities: '实体', attributes: '属性', relationships: '关系', dimensions: '维度', metrics: '指标' } as Record<string, string>)[key]}</span>)}</div></div>
          <section className="workbench-card"><div className="section-title"><div><strong>指标口径</strong><p>比例指标使用 ratio-of-sums，确保跨分组聚合仍然正确。</p></div><span>{selected.document.metrics.length} 个</span></div><div className="metric-grid">{selected.document.metrics.map((metric) => <article className="metric-card" key={metric.key}><div><strong>{metric.name}</strong><span>{metric.unit}</span></div><p>{metric.description}</p><Formula model={metric} /><small>可问法：{metric.aliases.join('、') || '标准名称'}</small></article>)}</div></section>
          <section className="workbench-card"><div className="section-title"><div><strong>物理字段映射</strong><p>系统只给候选和理由，最终映射必须由管理员确认。</p></div><span>{Object.keys(accepted).length} 已确认</span></div>
            <div className="mapping-controls"><select aria-label="数据源" value={sourceId ?? ''} onChange={(event) => { setSourceId(event.target.value || undefined); setSnapshotId(undefined) }}><option value="">选择数据源</option>{sources.data?.items.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select><select aria-label="目录快照" value={snapshotId ?? ''} onChange={(event) => setSnapshotId(event.target.value || undefined)} disabled={!sourceId}><option value="">选择目录快照</option>{snapshots.data?.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>v{snapshot.version} · {snapshot.status}</option>)}</select><button className="secondary-button" disabled={!Object.keys(accepted).length || selected.status !== 'draft' || saveDraft.isPending} onClick={() => void saveMappings()}>保存确认结果</button></div>
            {candidates.data && <div className="candidate-table">{candidates.data.candidates.map((item) => <label key={`${item.semantic_attribute}-${item.column_id}`}><input type="radio" name={item.semantic_attribute} checked={accepted[item.semantic_attribute]?.column_id === item.column_id} onChange={() => setAccepted((current) => ({ ...current, [item.semantic_attribute]: item }))} disabled={selected.status !== 'draft'} /><span><strong>{item.semantic_attribute}</strong><small>{item.schema_name}.{item.relation_name}.{item.column_name} · {Math.round(item.confidence * 100)}% · {item.reason}</small></span></label>)}{candidates.data.unmapped_attributes.length > 0 && <p className="warning-text">{candidates.data.unmapped_attributes.length} 个属性暂无可靠候选，需要人工补充字段或调整名称。</p>}</div>}
          </section>
          <footer className="publish-bar"><div><strong>发布检查</strong><span>实体与指标完整；已保存的映射必须全部确认并属于同一工作空间目录。</span></div>{selected.status === 'draft' ? <button className="primary-button" disabled={publish.isPending} onClick={() => void publish.mutateAsync(selected)}>发布不可变版本</button> : <button className="primary-button" disabled={createDraft.isPending} onClick={() => void createDraft.mutateAsync(selected)}>创建新版草稿</button>}</footer>
        </>}
      </main>
    </div>
  </section>
}
