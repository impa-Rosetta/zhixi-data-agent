import type { AnalysisArtifact, AnalysisRunView } from './types'

type QueryResult = {
  columns: string[]
  rows: unknown[][]
  rowCount: number
  truncated: boolean
  trust: 'trusted' | 'exploratory' | 'unknown'
}

export function AnalysisResultPanel({ view }: { view: AnalysisRunView }) {
  const artifact = view.artifacts.find((item) => item.artifact_type === 'query_result')
  if (!artifact) return null
  const result = readQueryResult(artifact)
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
