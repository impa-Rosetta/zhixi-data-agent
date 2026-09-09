import { nodeLabel } from './presentation'
import type { AnalysisEvent, AnalysisRunView } from './types'

type Props = {
  view?: AnalysisRunView
  events: AnalysisEvent[]
  connection: string
  streamError: string | null
}

export function AnalysisInspector({ view, events, connection, streamError }: Props) {
  if (!view) {
    return (
      <aside className="analysis-inspector">
        <header>
          <p className="analysis-kicker">执行与证据</p>
          <h2>运行详情</h2>
        </header>
        <div className="analysis-inspector-empty">
          选择任务后，这里会展示计划、工具调用和验证证据。
        </div>
      </aside>
    )
  }
  return (
    <aside className="analysis-inspector">
      <header>
        <div>
          <p className="analysis-kicker">执行与证据</p>
          <h2>运行详情</h2>
        </div>
        <span className={`analysis-connection ${connection}`}>
          {connectionLabel(connection)}
        </span>
      </header>
      {streamError && <p className="analysis-stream-error">事件流暂时中断，正在保留现有状态。</p>}

      <section className="analysis-inspector-section">
        <div className="analysis-section-title">
          <h3>执行计划</h3>
          <span>{view.steps.length} 步</span>
        </div>
        {view.steps.length === 0 ? (
          <p className="analysis-panel-message">计划尚未生成。</p>
        ) : (
          <ol className="analysis-step-list">
            {view.steps.map((step, index) => (
              <li className={step.status} key={step.id}>
                <span>{index + 1}</span>
                <div>
                  <strong>{step.tool_name}</strong>
                  <small>{stepStatusLabel(step.status)}</small>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="analysis-inspector-section">
        <div className="analysis-section-title">
          <h3>实时事件</h3>
          <span>#{view.last_event_sequence}</span>
        </div>
        <div className="analysis-event-list">
          {events.length === 0 && (
            <p className="analysis-panel-message">
              当前节点：{nodeLabel(view.run.current_node)}
            </p>
          )}
          {events.slice(-8).map((event) => (
            <div key={event.sequence}>
              <span>#{event.sequence}</span>
              <strong>{eventLabel(event.event_type)}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="analysis-inspector-section analysis-run-counters">
        <div><span>模型调用</span><strong>{view.run.model_calls}</strong></div>
        <div><span>工具调用</span><strong>{view.run.tool_calls}</strong></div>
        <div><span>Token</span><strong>{view.run.total_tokens}</strong></div>
      </section>

      <details className="analysis-technical-details">
        <summary>技术详情</summary>
        <dl>
          <div><dt>运行 ID</dt><dd>{view.run.id}</dd></div>
          <div><dt>当前节点</dt><dd>{view.run.current_node}</dd></div>
          <div>
            <dt>语义版本</dt>
            <dd>{displayIdentifier(view.run.frozen_versions.semantic_version_id)}</dd>
          </div>
          <div><dt>错误代码</dt><dd>{view.run.error_code ?? '无'}</dd></div>
        </dl>
      </details>
    </aside>
  )
}

function connectionLabel(connection: string): string {
  return {
    idle: '未连接',
    connecting: '连接中',
    live: '实时',
    closed: '已同步',
    error: '重连中',
  }[connection] ?? connection
}

function stepStatusLabel(status: string): string {
  return {
    pending: '等待',
    running: '执行中',
    succeeded: '完成',
    failed: '失败',
    skipped: '跳过',
  }[status] ?? status
}

function eventLabel(eventType: string): string {
  return {
    'run.created': '任务已创建',
    'run.node': '执行节点变化',
    'run.clarification_required': '需要补充',
    'run.confirmation_required': '需要确认',
    'run.confirmed': '计划已批准',
    'run.completed': '分析完成',
    'run.failed': '运行异常',
    'run.cancelled': '任务已取消',
    'message.accepted': '补充已接收',
  }[eventType] ?? eventType
}

function displayIdentifier(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : '未冻结'
}
