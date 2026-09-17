import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

import { AnalysisResultPanel } from './AnalysisResultPanel'
import { nodeLabel, runStatusLabel } from './presentation'
import type { AnalysisConversationView } from './types'

type Props = {
  view?: AnalysisConversationView
  userName?: string
  busy: boolean
  error: string | null
  onSubmit: (message: string, suggestionId?: string) => Promise<void>
  onCancel?: (turnId: string) => Promise<void>
}

export function ContinuousConversation({ view, userName, busy, error, onSubmit, onCancel }: Props) {
  const [message, setMessage] = useState('')
  const streamRef = useRef<HTMLElement>(null)
  const latest = view?.turns.at(-1)
  const running = latest && ['queued', 'running'].includes(latest.analysis.run.status)

  useEffect(() => {
    const stream = streamRef.current
    if (!stream) return
    if (typeof stream.scrollTo === 'function') {
      stream.scrollTo({ top: stream.scrollHeight, behavior: 'smooth' })
    } else {
      stream.scrollTop = stream.scrollHeight
    }
  }, [view?.turns.length, latest?.analysis.messages.length])

  const send = (suggestionId?: string, suggestedMessage?: string) => {
    const value = (suggestedMessage ?? message).trim()
    if (!value) return
    const submitted = suggestionId ? onSubmit(value, suggestionId) : onSubmit(value)
    void submitted.then(() => setMessage(''))
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    send()
  }
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      send()
    }
  }

  return (
    <main className="analysis-conversation analysis-continuous-conversation">
      <header className="analysis-run-header">
        <div>
          <p className="analysis-kicker">持续问析</p>
          <h2>{view?.conversation.title ?? '新的分析会话'}</h2>
        </div>
        {latest && (
          <span className={`analysis-status-chip ${latest.analysis.run.status}`}>
            {runStatusLabel[latest.analysis.run.status]}
          </span>
        )}
      </header>
      <section className="analysis-message-stream" aria-label="持续分析对话" ref={streamRef}>
        {!view && (
          <div className="analysis-welcome analysis-continuous-welcome">
            <span className="analysis-agent-mark">AI</span>
            <p className="analysis-kicker">可信企业数据 Agent</p>
            <h2>你好，{userName}，想分析什么？</h2>
            <p>每次回答后都可以在下方继续追问，不需要重新创建分析任务。</p>
          </div>
        )}
        {view?.turns.map(({ turn, analysis, suggested_follow_ups }) => (
          <section className="analysis-turn-block" key={turn.id} aria-label={`第 ${turn.sequence} 轮`}>
            {turn.relation === 'switch_topic' && (
              <div className="analysis-topic-switch" role="separator">
                已切换到新的分析主题，之前的筛选条件不会继续沿用
              </div>
            )}
            {analysis.messages.map((item) => (
              <article className={`analysis-message ${item.role}`} key={item.id}>
                <span>{item.role === 'user' ? '你' : 'Agent'}</span>
                <div>
                  <p>{item.content}</p>
                  <time dateTime={item.created_at}>{formatMessageTime(item.created_at)}</time>
                </div>
              </article>
            ))}
            {(analysis.run.status === 'queued' || analysis.run.status === 'running') && (
              <article className="analysis-progress-card" aria-live="polite">
                <span className="analysis-live-pulse" />
                <div>
                  <strong>
                    {turn.id === view.conversation.active_turn_id
                      ? nodeLabel(analysis.run.current_node)
                      : `已排队 · 第 ${turn.sequence} 轮`}
                  </strong>
                  <p>你可以继续输入下一条消息，Agent 会按发送顺序处理。</p>
                </div>
                {turn.id === view.conversation.active_turn_id && onCancel && (
                  <button type="button" className="secondary-button" onClick={() => void onCancel(turn.id)}>
                    取消当前分析
                  </button>
                )}
              </article>
            )}
            <AnalysisResultPanel view={analysis} />
            {turn.status === 'completed' && suggested_follow_ups.length > 0 && (
              <nav className="analysis-suggestions" aria-label={`第 ${turn.sequence} 轮推荐追问`}>
                <span>接下来可以问</span>
                {suggested_follow_ups.map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion.id}
                    onClick={() => send(suggestion.id, suggestion.message)}
                    disabled={busy}
                    title={suggestion.message}
                  >
                    {suggestion.label}
                  </button>
                ))}
              </nav>
            )}
          </section>
        ))}
      </section>
      <form className="analysis-composer analysis-persistent-composer" onSubmit={submit}>
        <label htmlFor="conversation-message">
          {view ? '继续追问' : '分析问题'}
        </label>
        <textarea
          id="conversation-message"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={keyDown}
          rows={3}
          maxLength={10_000}
          placeholder={running ? '继续输入，消息会按顺序排队执行…' : '输入问题或继续追问…'}
          disabled={view?.conversation.status === 'archived'}
        />
        <footer>
          <span>
            {view?.conversation.status === 'archived'
              ? '该会话已归档，只能查看'
              : running ? 'Agent 正在处理，发送后将自动排队' : 'Enter 换行 · Ctrl/⌘ + Enter 发送'}
          </span>
          <button
            type="submit"
            className="primary-button"
            disabled={busy || !message.trim() || view?.conversation.status === 'archived'}
          >
            {busy ? '正在发送…' : running ? '加入队列' : '发送'}
          </button>
        </footer>
        {error && <p className="analysis-inline-error" role="alert">{error}</p>}
      </form>
    </main>
  )
}

function formatMessageTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
