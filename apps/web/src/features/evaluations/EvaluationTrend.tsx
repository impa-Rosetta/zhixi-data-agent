import type { EvaluationRun } from './api'

type Point = { id: string; createdAt: string; coverage: number; passRate: number }

function rate(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? value : null
}

function comparable(a: EvaluationRun, b: EvaluationRun): boolean {
  return a.workspace_id === b.workspace_id
    && a.track === b.track
    && a.suite_version === b.suite_version
    && a.suite_digest === b.suite_digest
    && a.dataset_id === b.dataset_id
    && a.semantic_version === b.semantic_version
    && a.model_version === b.model_version
    && a.tool_version === b.tool_version
    && a.prompt_version === b.prompt_version
}

function points(current: EvaluationRun, recent: EvaluationRun[]): Point[] {
  return recent.slice(0, 30).flatMap((item) => {
    if (item.status !== 'completed' || !comparable(current, item)) return []
    const coverage = rate(item.summary.coverage_rate)
    const passRate = rate(item.summary.evaluated_pass_rate)
    if (coverage === null || passRate === null) return []
    return [{ id: item.id, createdAt: item.created_at, coverage, passRate }]
  }).sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt) || a.id.localeCompare(b.id))
}

function line(data: Point[], field: 'coverage' | 'passRate'): string {
  return data.map((item, index) => {
    const x = 20 + (index * 560) / (data.length - 1)
    const y = 120 - item[field] * 100
    return `${x},${y}`
  }).join(' ')
}

export function EvaluationTrend({ current, recent }: {
  current: EvaluationRun; recent: EvaluationRun[]
}) {
  const data = points(current, recent)
  return <section className="evaluation-trend" aria-label="历史趋势">
    <h3>历史趋势</h3>
    <p>仅统计最近最多 30 次运行中，同轨道、同案例集与数据、语义、模型、工具、提示版本的已完成记录。未评估案例不计入已评估通过率；横轴按运行顺序排列，不表示等时间间隔。</p>
    {data.length < 2 ? <p>暂无可比趋势</p> : <>
      <div className="evaluation-trend-legend"><span>覆盖率</span><span>已评估通过率</span></div>
      <svg viewBox="0 0 600 140" role="img" aria-label="最近同版本评测覆盖率与已评估通过率趋势">
        <line x1="20" y1="20" x2="580" y2="20" className="evaluation-trend-grid" />
        <line x1="20" y1="120" x2="580" y2="120" className="evaluation-trend-grid" />
        <polyline points={line(data, 'coverage')} className="evaluation-trend-coverage" />
        <polyline points={line(data, 'passRate')} className="evaluation-trend-pass" />
      </svg>
      <div className="evaluation-table"><table><thead><tr><th>运行时间</th><th>覆盖率</th><th>已评估通过率</th></tr></thead>
        <tbody>{data.map((item) => <tr key={item.id}><td>{new Date(item.createdAt).toLocaleString('zh-CN')}</td><td>{(item.coverage * 100).toFixed(1)}%</td><td>{(item.passRate * 100).toFixed(1)}%</td></tr>)}</tbody>
      </table></div>
    </>}
  </section>
}
