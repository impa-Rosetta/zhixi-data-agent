import { lazy, Suspense } from 'react'

import type { AnalysisArtifact, AnalysisRunView } from './types'

const AnalysisChart = lazy(async () => {
  const module = await import('./AnalysisChart')
  return { default: module.AnalysisChart }
})

type QueryResult = {
  columns: string[]
  rows: unknown[][]
  rowCount: number
  truncated: boolean
  trust: 'trusted' | 'exploratory' | 'unknown'
}

export function AnalysisResultPanel({ view }: { view: AnalysisRunView }) {
  const capability = view.artifacts.find((item) => item.artifact_type === 'assistant_message')
  if (capability) return <CapabilityResult artifact={capability} view={view} />
  const catalog = view.artifacts.find((item) => item.artifact_type === 'catalog_result')
  if (catalog) return <CatalogResult artifact={catalog} view={view} />
  const artifact = view.artifacts.find((item) => item.artifact_type === 'query_result')
  if (!artifact) return null
  const result = readQueryResult(artifact)
  const analysis = view.artifacts.find((item) =>
    item.artifact_type === 'analysis_summary' && item.summary.source_artifact_id === artifact.id)
  const chart = view.artifacts.find((item) =>
    item.artifact_type === 'chart_spec' && item.summary.source_artifact_id === artifact.id)
  const linkedEvidence = view.evidence.find((item) => item.artifact_id === artifact.id)
  const validationPassed = view.validations.some((item) => item.outcome === 'passed')

  return (
    <section className="analysis-result" aria-label="分析结果">
      <header>
        <div>
          <p className="analysis-kicker">结构化分析产物</p>
          <h3>查询结果</h3>
        </div>
        <div className="analysis-result-badges">
          <span className={`analysis-trust ${result.trust}`}>
            {trustLabel(result.trust)}
          </span>
          <span>{result.rowCount} 行</span>
          {result.truncated && <span className="warning">结果已截断</span>}
        </div>
      </header>

      {result.rows.length === 0 ? (
        <div className="analysis-result-empty">
          查询已成功执行，但当前筛选范围内没有数据。
        </div>
      ) : result.rows.length === 1 ? (
        <div className="analysis-metric-grid">
          {result.columns.map((column, index) => (
            <article key={`${column}-${index}`}>
              <span>{column}</span>
              <strong title={formatCell(result.rows[0]?.[index])}>
                {formatCell(result.rows[0]?.[index])}
              </strong>
            </article>
          ))}
        </div>
      ) : (
        <div className="analysis-result-table-wrap">
          <table className="analysis-result-table">
            <thead><tr>{result.columns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead>
            <tbody>
              {result.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {result.columns.map((column, columnIndex) => (
                    <td key={`${column}-${columnIndex}`} title={formatCell(row[columnIndex])}>
                      {formatCell(row[columnIndex])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {analysis && <DescriptiveAnalysis artifact={analysis} />}
      {chart && (
        <Suspense fallback={<div className="analysis-chart-loading" role="status">正在加载图表…</div>}>
          <AnalysisChart artifact={chart} source={artifact} />
        </Suspense>
      )}

      <footer>
        <span className={validationPassed ? 'validation-passed' : 'validation-pending'}>
          {validationPassed ? '✓ 证据校验通过' : '证据校验待确认'}
        </span>
        {linkedEvidence && (
          <a href={`#evidence-${linkedEvidence.id}`}>定位证据</a>
        )}
      </footer>
    </section>
  )
}

function DescriptiveAnalysis({ artifact }: { artifact: AnalysisArtifact }) {
  const rawColumns = artifact.summary.numeric_columns
  const columns = Array.isArray(rawColumns)
    ? rawColumns.filter((item): item is Record<string, unknown> =>
      typeof item === 'object' && item !== null && !Array.isArray(item),
    ).slice(0, 6)
    : []
  if (columns.length === 0) return null
  return (
    <section className="analysis-statistics" aria-label="描述统计">
      <header>
        <div><p className="analysis-kicker">验证结果派生</p><h4>描述统计</h4></div>
        <span>{numberValue(artifact.summary.row_count)} 行</span>
      </header>
      <div>
        {columns.map((column, index) => (
          <article key={textValue(column.field) || index}>
            <strong>{textValue(column.field) || '数值字段'}</strong>
            <dl>
              <div><dt>均值</dt><dd>{formatCell(column.mean)}</dd></div>
              <div><dt>中位数</dt><dd>{formatCell(column.median)}</dd></div>
              <div><dt>最小值</dt><dd>{formatCell(column.minimum)}</dd></div>
              <div><dt>最大值</dt><dd>{formatCell(column.maximum)}</dd></div>
              <div><dt>标准差</dt><dd>{formatCell(column.standard_deviation)}</dd></div>
              <div><dt>缺失数</dt><dd>{formatCell(column.null_count)}</dd></div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  )
}
function CapabilityResult({ artifact, view }: { artifact: AnalysisArtifact; view: AnalysisRunView }) {
  const message = textValue(artifact.summary.message)
  const available = stringList(artifact.summary.available)
  const planned = stringList(artifact.summary.planned)
  const examples = stringList(artifact.summary.examples)
  const boundaries = stringList(artifact.summary.boundaries)
  return (
    <section className="analysis-result analysis-capability-result" aria-label="Agent 能力说明">
      <header>
        <div><p className="analysis-kicker">版本化产品能力</p><h3>Agent 能力说明</h3></div>
        <div className="analysis-result-badges">
          <span>清单 v{textValue(artifact.summary.manifest_version) || '未知'}</span>
        </div>
      </header>
      <p className="analysis-answer-message">{message || '能力说明暂不可用。'}</p>
      <div className="analysis-capability-columns">
        <ResultList title="当前可用" items={available} />
        <ResultList title="尚未开放" items={planned} />
      </div>
      {examples.length > 0 && <ResultList title="可以这样问" items={examples} />}
      {boundaries.length > 0 && <ResultList title="安全边界" items={boundaries} />}
      <ResultFooter artifact={artifact} view={view} />
    </section>
  )
}

function CatalogResult({ artifact, view }: { artifact: AnalysisArtifact; view: AnalysisRunView }) {
  const sources = objectList(artifact.summary.sources)
  return (
    <section className="analysis-result analysis-catalog-result" aria-label="数据目录结果">
      <header>
        <div><p className="analysis-kicker">授权发布快照</p><h3>数据目录结果</h3></div>
        <div className="analysis-result-badges">
          <span>{numberValue(artifact.summary.source_count)} 个数据源</span>
          <span>{numberValue(artifact.summary.relation_count)} 个表或视图</span>
          {artifact.summary.truncated === true && <span className="warning">结果已截断</span>}
        </div>
      </header>
      <p className="analysis-answer-message">{textValue(artifact.summary.message)}</p>
      <div className="analysis-catalog-sources">
        {sources.length === 0 && <div className="analysis-result-empty">没有匹配的目录对象。</div>}
        {sources.map((source, sourceIndex) => (
          <article key={textValue(source.id) || sourceIndex}>
            <header>
              <div><strong>{textValue(source.name) || '未命名数据源'}</strong><small>{textValue(source.source_type)}</small></div>
              <span>快照 v{numberValue(source.snapshot_version)}</span>
            </header>
            {objectList(source.relations).map((relation, relationIndex) => (
              <section key={[textValue(relation.schema), textValue(relation.name), String(relationIndex)].join('-')}>
                <h4>{[textValue(relation.schema), textValue(relation.name)].filter(Boolean).join('.')}</h4>
                <p>{textValue(relation.comment) || textValue(relation.relation_type)}</p>
                <div className="analysis-catalog-fields">
                  {objectList(relation.columns).map((column, columnIndex) => (
                    <span key={[textValue(column.name), String(columnIndex)].join('-')}>
                      <strong>{textValue(column.name)}</strong>
                      <small>{textValue(column.data_type)} · {column.nullable === true ? '可空' : '必填'}</small>
                    </span>
                  ))}
                </div>
              </section>
            ))}
          </article>
        ))}
      </div>
      {artifact.summary.samples_included === false && (
        <p className="analysis-catalog-safety">不包含数据样例，仅展示授权目录结构。</p>
      )}
      <ResultFooter artifact={artifact} view={view} />
    </section>
  )
}

function ResultList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return <section className="analysis-result-list"><h4>{title}</h4><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></section>
}

function ResultFooter({ artifact, view }: { artifact: AnalysisArtifact; view: AnalysisRunView }) {
  const linkedEvidence = view.evidence.find((item) => item.artifact_id === artifact.id)
  const validationPassed = view.validations.some((item) => item.outcome === 'passed')
  return (
    <footer>
      <span className={validationPassed ? 'validation-passed' : 'validation-pending'}>
        {validationPassed ? '✓ 证据校验通过' : '证据校验待确认'}
      </span>
      {linkedEvidence && <a href={'#evidence-' + linkedEvidence.id}>定位证据</a>}
    </footer>
  )
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function objectList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
      typeof item === 'object' && item !== null && !Array.isArray(item),
    )
    : []
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function readQueryResult(artifact: AnalysisArtifact): QueryResult {
  const rawColumns = artifact.summary.columns
  const columns = Array.isArray(rawColumns)
    ? rawColumns.filter((item): item is string => typeof item === 'string')
    : []
  const rawRows = artifact.summary.rows
  const rows = Array.isArray(rawRows)
    ? rawRows.filter((item): item is unknown[] => Array.isArray(item))
    : []
  const rawCount = artifact.summary.row_count
  const rawTrust = artifact.summary.trust
  return {
    columns: columns.length > 0
      ? columns
      : Array.from({ length: Math.max(0, ...rows.map((row) => row.length)) }, (_, index) => `字段 ${index + 1}`),
    rows,
    rowCount: typeof rawCount === 'number' && Number.isFinite(rawCount)
      ? Math.max(0, rawCount)
      : rows.length,
    truncated: artifact.summary.truncated === true,
    trust: rawTrust === 'trusted' || rawTrust === 'exploratory' ? rawTrust : 'unknown',
  }
}

function trustLabel(trust: QueryResult['trust']): string {
  return { trusted: '可信结果', exploratory: '探索结果', unknown: '未标记可信度' }[trust]
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isFinite(value)
      ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 8 }).format(value)
      : '—'
  }
  if (typeof value === 'string') return value || '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  try {
    return JSON.stringify(value)
  } catch {
    return '无法显示'
  }
}
