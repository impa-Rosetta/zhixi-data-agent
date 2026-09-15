import { formatRunTime } from './presentation'
import type { AnalysisConversationSummary } from './types'

type Props = {
  items: AnalysisConversationSummary[]
  selectedId?: string
  loading: boolean
  onSelect: (id: string) => void
  onNew: () => void
}

const statusLabel: Record<string, string> = {
  queued: '等待执行',
  running: '正在分析',
  waiting_for_user: '等待回复',
  completed: '已回答',
  failed: '可继续提问',
  cancelled: '已取消',
}

export function ConversationList({ items, selectedId, loading, onSelect, onNew }: Props) {
  return (
    <aside className="analysis-run-list" aria-label="分析会话">
      <header>
        <div><span className="analysis-kicker">对话空间</span><h2>分析会话</h2></div>
        <button type="button" className="analysis-new-button" onClick={onNew}>新建</button>
      </header>
      <div className="analysis-run-items">
        {loading && <p className="analysis-panel-message">正在载入会话…</p>}
        {!loading && items.length === 0 && (
          <div className="analysis-list-empty">
            <strong>还没有分析会话</strong>
            <p>提出第一个问题后，可以在同一会话持续追问。</p>
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
              <span className={`analysis-status-dot ${item.active_turn_status ?? 'completed'}`} />
              <strong>{item.title}</strong>
            </span>
            <span className="analysis-conversation-preview">
              {item.last_message_preview ?? '等待第一个问题'}
            </span>
            <span className="analysis-run-item-meta">
              <span>{statusLabel[item.active_turn_status ?? 'completed']}</span>
              <time dateTime={item.updated_at}>{formatRunTime(item.updated_at)}</time>
            </span>
          </button>
        ))}
      </div>
    </aside>
  )
}
