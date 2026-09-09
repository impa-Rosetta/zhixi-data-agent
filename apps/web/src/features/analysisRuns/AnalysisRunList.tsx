import { formatRunTime, runStatusLabel } from './presentation'
import type { AnalysisRunSummary } from './types'

type Props = {
  items: AnalysisRunSummary[]
  selectedId?: string
  loading: boolean
  onSelect: (id: string) => void
  onNew: () => void
}

export function AnalysisRunList({
  items,
  selectedId,
  loading,
  onSelect,
  onNew,
}: Props) {
  return (
    <aside className="analysis-run-list" aria-label="分析任务">
      <header>
        <div>
          <span className="analysis-kicker">任务空间</span>
          <h2>分析任务</h2>
        </div>
        <button type="button" className="analysis-new-button" onClick={onNew}>
          新建
        </button>
      </header>
      <div className="analysis-run-items">
        {loading && <p className="analysis-panel-message">正在载入任务…</p>}
        {!loading && items.length === 0 && (
          <div className="analysis-list-empty">
            <strong>还没有分析任务</strong>
            <p>提出第一个问题后，运行记录会保存在这里。</p>
          </div>
        )}
        {items.map((item) => (
          <button
            type="button"
            className={`analysis-run-item ${item.id === selectedId ? 'active' : ''}`}
            aria-current={item.id === selectedId ? 'page' : undefined}
            onClick={() => onSelect(item.id)}
            key={item.id}
          >
            <span className="analysis-run-item-head">
              <span className={`analysis-status-dot ${item.status}`} />
              <strong>{item.goal || '未命名分析'}</strong>
            </span>
            <span className="analysis-run-item-meta">
              <span>{runStatusLabel[item.status]}</span>
              <time dateTime={item.updated_at}>{formatRunTime(item.updated_at)}</time>
            </span>
          </button>
        ))}
      </div>
    </aside>
  )
}
