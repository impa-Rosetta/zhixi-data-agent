import { useState, type FormEvent } from 'react'

import { errorLabel, nodeLabel, runStatusLabel } from './presentation'
import { AnalysisResultPanel } from './AnalysisResultPanel'
import type { AnalysisRunView } from './types'

type Props = {
  view?: AnalysisRunView
  userName?: string
  busy: boolean
  actionError: string | null
  onCreate: (message: string) => Promise<void>
  onMessage: (message: string) => Promise<void>
  onConfirm: (approved: boolean) => Promise<void>
  onCancel: () => Promise<void>
  onRetry: () => Promise<void>
  onNew: () => void
}

export function AnalysisConversation(props: Props) {
  const [question, setQuestion] = useState('')
  const [clarification, setClarification] = useState('')

  const submitQuestion = (event: FormEvent) => {
    event.preventDefault()
    const message = question.trim()
    if (!message) return
    void props.onCreate(message).then(() => setQuestion(''))
  }
  const submitClarification = (event: FormEvent) => {
    event.preventDefault()
    const message = clarification.trim()
    if (!message) return
    void props.onMessage(message).then(() => setClarification(''))
  }

  if (!props.view) {
    return (
      <main className="analysis-conversation analysis-conversation-empty">
        <div className="analysis-welcome">
          <span className="analysis-agent-mark">AI</span>
          <p className="analysis-kicker">可信企业数据 Agent</p>
          <h2>可信分析，从一个问题开始</h2>
          <p>
            你好，{props.userName}。Agent 会绑定已发布语义模型，制定受控计划，
            并只通过授权工具访问数据。
          </p>
        </div>
        <form className="analysis-composer" onSubmit={submitQuestion}>
          <label htmlFor="analysis-question">分析问题</label>
          <textarea
            id="analysis-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="例如：本月哪条产线的不良率最高？与上月相比变化如何？"
            rows={4}
            maxLength={10_000}
          />
          <footer>
            <span>真实运行 · 语义约束 · 全程留痕</span>
            <button
              type="submit"
              className="primary-button"
              disabled={props.busy || question.trim().length < 2}
            >
              {props.busy ? '正在创建…' : '开始分析'}
            </button>
          </footer>
        </form>
        {props.actionError && <p className="analysis-inline-error">{props.actionError}</p>}
      </main>
    )
  }

  const { run, messages, plan } = props.view
  const failure = errorLabel(run.error_code)
  return (
    <main className="analysis-conversation">
      <header className="analysis-run-header">
        <div>
          <p className="analysis-kicker">当前分析</p>
          <h2>{displayValue(run.context.goal, plan?.goal ?? '数据分析任务')}</h2>
        </div>
        <span className={`analysis-status-chip ${run.status}`}>
          {runStatusLabel[run.status]}
        </span>
      </header>

      <section className="analysis-message-stream" aria-label="分析对话">
        {messages.map((message) => (
          <article className={`analysis-message ${message.role}`} key={message.id}>
            <span>{message.role === 'user' ? '你' : 'Agent'}</span>
            <div>
              <p>{message.content}</p>
              <time dateTime={message.created_at}>{formatMessageTime(message.created_at)}</time>
            </div>
          </article>
        ))}
        {(run.status === 'queued' || run.status === 'running') && (
          <article className="analysis-progress-card">
            <span className="analysis-live-pulse" />
            <div>
              <strong>{nodeLabel(run.current_node)}</strong>
              <p>Agent 正在受控执行；刷新页面或短时断网不会丢失任务进度。</p>
            </div>
          </article>
        )}
        {failure && <div className="analysis-run-warning">{failure}</div>}
        <AnalysisResultPanel view={props.view} />
      </section>

      {run.status === 'waiting_for_clarification' && (
        <form className="analysis-response-box" onSubmit={submitClarification}>
          <div>
            <strong>Agent 需要你补充信息</strong>
            <p>请明确指标、时间范围或分析对象，系统会从当前检查点继续。</p>
          </div>
          <label htmlFor="analysis-clarification">补充说明</label>
          <textarea
            id="analysis-clarification"
            value={clarification}
            onChange={(event) => setClarification(event.target.value)}
            rows={3}
            maxLength={10_000}
          />
          <button
            type="submit"
            className="primary-button"
            disabled={props.busy || !clarification.trim()}
          >
            提交并继续
          </button>
        </form>
      )}

      {run.status === 'waiting_for_confirmation' && (
        <section className="analysis-confirmation">
          <div>
            <p className="analysis-kicker">人工确认门</p>
            <h3>计划已暂停，等待明确授权</h3>
            <p>{plan?.goal ?? '当前计划'} · {props.view.steps.length} 个受控步骤</p>
          </div>
          <footer>
            <button
              type="button"
              className="secondary-button"
              disabled={props.busy}
              onClick={() => void props.onConfirm(false)}
            >
              拒绝计划
            </button>
            <button
              type="button"
              className="primary-button"
              disabled={props.busy}
              onClick={() => void props.onConfirm(true)}
            >
              批准并执行
            </button>
          </footer>
        </section>
      )}

      <footer className="analysis-run-actions">
        {(run.status === 'queued' || run.status === 'running') && (
          <button
            type="button"
            className="secondary-button"
            disabled={props.busy}
            onClick={() => void props.onCancel()}
          >
            取消任务
          </button>
        )}
        {run.status === 'failed_retryable' && (
          <button
            type="button"
            className="primary-button"
            disabled={props.busy}
            onClick={() => void props.onRetry()}
          >
            从检查点重试
          </button>
        )}
        {['completed', 'failed', 'cancelled'].includes(run.status) && (
          <button type="button" className="primary-button" onClick={props.onNew}>
            发起新分析
          </button>
        )}
        {props.actionError && <p className="analysis-inline-error">{props.actionError}</p>}
      </footer>
    </main>
  )
}

function formatMessageTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function displayValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}
