import { useMemo, useState } from 'react'

import './QueryLabPage.css'

import { useAuth } from '../features/auth/context'
import { useDataSources } from '../features/dataSources/api'
import { useCompileSemanticQuery, useExecuteValidatedQuery, useQueryHistory, useValidateExploratoryQuery, type QueryExecution, type ValidatedQuery } from '../features/queries/api'
import { useSemanticModels } from '../features/semantic/api'

export function QueryLabPage() {
  const { workspace } = useAuth()
  const workspaceId = workspace?.id
  const models = useSemanticModels(workspaceId)
  const sources = useDataSources(workspaceId)
  const history = useQueryHistory(workspaceId)
  const compile = useCompileSemanticQuery(workspaceId)
  const validate = useValidateExploratoryQuery(workspaceId)
  const execute = useExecuteValidatedQuery(workspaceId)
  const published = useMemo(() => models.data?.items.filter((item) => item.status === 'published') ?? [], [models.data])
  const [mode, setMode] = useState<'trusted' | 'exploratory'>('trusted')
  const [modelId, setModelId] = useState('')
  const [metrics, setMetrics] = useState<string[]>([])
  const [dimension, setDimension] = useState('')
  const [grain, setGrain] = useState('')
  const [comparison, setComparison] = useState<'none' | 'previous_period'>('none')
  const [sourceId, setSourceId] = useState('')
  const [sql, setSql] = useState('')
  const [validated, setValidated] = useState<ValidatedQuery | null>(null)
  const [result, setResult] = useState<QueryExecution | null>(null)
  const activeModelId = modelId || published[0]?.id || ''
  const model = published.find((item) => item.id === activeModelId)
  const activeSourceId = sourceId || sources.data?.items.find((item) => item.status === 'ready' || item.status === 'degraded')?.id || ''

  async function prepare() {
    setResult(null)
    if (mode === 'trusted') {
      if (!activeModelId || metrics.length === 0) return
      const item = await compile.mutateAsync({ semantic_model_id: activeModelId, metrics, dimensions: dimension ? [dimension] : [], filters: [], time_grain: grain || null, comparison, sort: dimension ? [{ field: dimension, direction: 'asc' }] : [], limit: 200 })
      setValidated(item)
    } else {
      if (!activeSourceId || !sql.trim()) return
      setValidated(await validate.mutateAsync({ data_source_id: activeSourceId, sql, limit: 200 }))
    }
  }

  async function run() { if (validated) setResult(await execute.mutateAsync(validated.id)) }
  const busy = compile.isPending || validate.isPending || execute.isPending
  const error = compile.error ?? validate.error ?? execute.error

  return <div className="page query-lab">
    <div className="page-heading"><div><p className="eyebrow">M4 · GOVERNED QUERY ENGINE</p><h1>可信查询实验室</h1><p>语义查询与探索 SQL 共用同一安全门禁；执行器只接受短时有效的验证 ID。</p></div><span className="role-chip">SQLGlot 安全引擎</span></div>
    <div className="query-mode-tabs"><button className={mode === 'trusted' ? 'active' : ''} onClick={() => { setMode('trusted'); setValidated(null); setResult(null) }}>可信语义查询</button><button className={mode === 'exploratory' ? 'active warning' : ''} onClick={() => { setMode('exploratory'); setValidated(null); setResult(null) }}>探索 SQL</button></div>
    <section className="query-workbench">
      <div className="query-builder">
        {mode === 'trusted' ? <>
          <label>已发布语义模型<select value={activeModelId} onChange={(event) => { setModelId(event.target.value); setMetrics([]); setDimension(''); setValidated(null); setResult(null) }}><option value="">请选择</option>{published.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.published_version}</option>)}</select></label>
          {!published.length && <div className="query-empty">暂无已发布模型。请先在“语义模型”中完成字段映射并发布。</div>}
          {model && <><fieldset><legend>指标（可多选）</legend><div className="query-option-grid">{model.document.metrics.map((item) => <label key={item.key}><input type="checkbox" checked={metrics.includes(item.key)} onChange={(event) => setMetrics(event.target.checked ? [...metrics, item.key] : metrics.filter((key) => key !== item.key))} /><span><strong>{item.name}</strong><small>{item.key} · {item.unit}</small></span></label>)}</div></fieldset>
          <div className="query-row"><label>分析维度<select value={dimension} onChange={(event) => { setDimension(event.target.value); setGrain(''); setComparison('none') }}><option value="">不分组</option>{model.document.dimensions.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label>时间粒度<select value={grain} disabled={!dimension} onChange={(event) => setGrain(event.target.value)}><option value="">原始粒度</option><option value="day">日</option><option value="week">周</option><option value="month">月</option><option value="quarter">季度</option><option value="year">年</option></select></label><label>周期比较<select value={comparison} disabled={!grain} onChange={(event) => setComparison(event.target.value as 'none' | 'previous_period')}><option value="none">无</option><option value="previous_period">上一周期</option></select></label></div></>}
        </> : <><div className="exploratory-warning"><strong>探索结果不等于可信口径</strong><span>系统仍会阻断写操作、系统表、危险函数、笛卡尔积和未授权对象。</span></div><label>目标数据源<select value={activeSourceId} onChange={(event) => { setSourceId(event.target.value); setValidated(null); setResult(null) }}><option value="">请选择</option>{sources.data?.items.filter((item) => item.status === 'ready' || item.status === 'degraded').map((item) => <option key={item.id} value={item.id}>{item.name} · {item.source_type}</option>)}</select></label><label>只读 SQL<textarea className="sql-editor" value={sql} onChange={(event) => setSql(event.target.value)} placeholder="SELECT ... FROM schema.table" spellCheck={false} /></label></>}
        {error && <p className="query-error">{error instanceof Error ? error.message : '请求失败'}</p>}
        <button className="primary-button" disabled={busy || (mode === 'trusted' ? !activeModelId || !metrics.length : !activeSourceId || !sql.trim())} onClick={() => void prepare()}>{busy ? '处理中…' : '生成并安全校验'}</button>
      </div>
      <div className="query-validation">
        <header><div><p className="eyebrow">VALIDATION GATE</p><h2>执行凭证</h2></div>{validated && <span className={`trust-badge ${validated.trust}`}>{validated.trust === 'trusted' ? '可信' : '探索'}</span>}</header>
        {!validated ? <div className="query-empty">选择口径并通过校验后，这里会显示不可绕过的查询凭证。</div> : <><dl><div><dt>验证 ID</dt><dd><code>{validated.id}</code></dd></div><div><dt>SQL 摘要</dt><dd><code>{validated.digest.slice(0, 16)}…</code></dd></div><div><dt>目录快照</dt><dd><code>{validated.snapshot_id.slice(0, 8)}</code></dd></div><div><dt>依赖对象</dt><dd>{validated.dependencies.join('、')}</dd></div></dl><pre>{validated.sql}</pre><button className="primary-button execute" disabled={busy} onClick={() => void run()}>仅凭验证 ID 执行</button></>}
      </div>
    </section>
    {result && <ResultTable result={result} />}
    <section className="query-history"><header><div><p className="eyebrow">EVIDENCE</p><h2>最近执行与证据</h2></div><span>{history.data?.length ?? 0} 条</span></header>{!history.data?.length ? <div className="query-empty">暂无执行记录</div> : <div>{history.data.map((item) => <article key={item.id}><span className={`trust-badge ${item.trust}`}>{item.trust === 'trusted' ? '可信' : '探索'}</span><div><strong>{item.status === 'succeeded' ? `${item.row_count} 行结果` : item.error_code}</strong><small>{new Date(item.started_at).toLocaleString()} · 验证 ID {item.validated_query_id.slice(0, 8)}</small></div><code>{item.evidence_digest?.slice(0, 16) ?? '无证据摘要'}…</code></article>)}</div>}</section>
  </div>
}

function ResultTable({ result }: { result: QueryExecution }) {
  return <section className="query-results"><header><div><p className="eyebrow">READ-ONLY RESULT</p><h2>查询结果</h2></div><span>{result.row_count} 行{result.truncated ? ' · 已截断' : ''}</span></header>{result.status === 'failed' ? <div className="query-error">执行失败：{result.error_code}</div> : <div className="result-scroll"><table><thead><tr>{result.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{result.rows.map((row, index) => <tr key={index}>{row.map((value, columnIndex) => <td key={columnIndex}>{formatCell(value)}</td>)}</tr>)}</tbody></table></div>}<footer>证据摘要：<code>{result.evidence_digest}</code></footer></section>
}

function formatCell(value: unknown): string {
  if (value === null) return 'NULL'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return value.toString()
  if (typeof value === 'object') return JSON.stringify(value) ?? '—'
  return '—'
}
