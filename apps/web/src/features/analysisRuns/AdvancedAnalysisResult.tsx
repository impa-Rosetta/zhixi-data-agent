import type { AnalysisArtifact } from './types'

function numeric(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(value)
    : '—'
}

export function AdvancedAnalysisResult({ artifact }: { artifact: AnalysisArtifact }) {
  const result = artifact.summary
  const correlation = artifact.artifact_type === 'correlation_result'
  const points = Array.isArray(result.anomalies) ? result.anomalies.filter(
    (item): item is Record<string, unknown> => typeof item === 'object' && item !== null && !Array.isArray(item),
  ) : []
  return (
    <section className="analysis-statistics" aria-label={correlation ? '相关性分析' : 'IQR 异常检测'}>
      <header>
        <div><p className="analysis-kicker">验证结果派生</p><h4>{correlation ? '相关性分析' : 'IQR 异常检测'}</h4></div>
        <span>{correlation ? (result.method === 'spearman' ? 'Spearman' : 'Pearson') : 'IQR'}</span>
      </header>
      <div><article><dl>
        {correlation ? <div><dt>相关系数</dt><dd>{numeric(result.coefficient)}</dd></div> : <>
          <div><dt>参考下界</dt><dd>{numeric(result.lower_bound)}</dd></div>
          <div><dt>参考上界</dt><dd>{numeric(result.upper_bound)}</dd></div>
          <div><dt>异常候选</dt><dd>{points.length}</dd></div>
        </>}
        <div><dt>有效样本</dt><dd>{numeric(result.sample_count)}</dd></div>
        <div><dt>缺失排除</dt><dd>{numeric(result.dropped_count)}</dd></div>
      </dl></article></div>
      <p className="analysis-answer-message">{typeof result.warning === 'string' ? result.warning : '请结合业务背景复核结果。'}</p>
      {!correlation && points.length > 0 && <div className="analysis-result-table-wrap">
        <table className="analysis-result-table">
          <thead><tr><th>来源位置</th><th>数值</th><th>方向</th></tr></thead>
          <tbody>{points.slice(0, 40).map((point, index) => <tr key={index}>
            <td>{typeof point.row_index === 'number' && Number.isInteger(point.row_index) && point.row_index >= 0
              ? `第 ${point.row_index + 1} 行` : '—'}</td>
            <td>{numeric(point.value)}</td><td>{point.direction === 'above' ? '高于上界' : point.direction === 'below' ? '低于下界' : '—'}</td>
          </tr>)}</tbody>
        </table>
        {points.length > 40 && <p>这里只展示前40个候选，完整结果保留在分析产物中。</p>}
      </div>}
    </section>
  )
}
