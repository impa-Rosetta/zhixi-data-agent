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

      <section className="analysis-inspector-section">
        <div className="analysis-section-title">
          <h3>Evidence</h3>
          <span>{view.evidence.length} 条</span>
        </div>
        {view.evidence.length === 0 ? (
          <p className="analysis-panel-message">结果产生后会固化证据引用。</p>
        ) : (
          <div className="analysis-evidence-list">
            {view.evidence.map((item) => (
              <article id={`evidence-${item.id}`} tabIndex={-1} key={item.id}>
                <header>
                  <strong>{evidenceLabel(item.evidence_type)}</strong>
                  <span>{shortDigest(item.evidence_digest)}</span>
                </header>
                <dl>
                  <EvidenceField label="查询" value={item.reference.validated_query_id} />
                  <EvidenceField label="执行" value={item.reference.execution_id} />
                  <EvidenceField label="语义版本" value={item.reference.semantic_version_id} />
                  <EvidenceField label="目录快照" value={item.reference.snapshot_ids} />
                  <EvidenceField label="能力清单版本" value={item.reference.manifest_version} />
                  <EvidenceField label="快照 ID" value={item.reference.snapshot_id} />
                  <EvidenceField label="快照版本" value={item.reference.snapshot_version} />
                  <EvidenceField label="数据源 ID" value={item.reference.data_source_id} />
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="analysis-inspector-section">
        <div className="analysis-section-title">
          <h3>验证结论</h3>
          <span>{view.validations.length} 项</span>
        </div>
        <div className="analysis-validation-list">
          {view.validations.length === 0 && (
            <p className="analysis-panel-message">尚无验证记录。</p>
          )}
          {view.validations.map((item) => (
            <div className={item.outcome} key={item.id}>
              <span>{item.outcome === 'passed' ? '✓' : '!'}</span>
              <p>
                <strong>{validationLabel(item.validation_type)}</strong>
                <small>{validationOutcome(item.outcome)} · {item.findings.length} 个发现</small>
              </p>
            </div>
          ))}
        </div>
      </section>

      <details className="analysis-technical-details">
        <summary>技术详情</summary>
        <dl>
          <div><dt>运行 ID</dt><dd>{view.run.id}</dd></div>
          <div><dt>当前节点</dt><dd>{view.run.current_node}</dd></div>
          <div><dt>任务路由</dt><dd>{displayRoute(view.run.context.route)}</dd></div>
          <div><dt>Intent 修订</dt><dd>{displayIdentifier(view.run.context.intent_revision)}</dd></div>
          <div><dt>默认范围</dt><dd>{displayDefaults(view.run.context.defaults_applied)}</dd></div>
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
    'run.route_selected': '路由已选择',
    'run.defaults_applied': '已应用默认范围',
    'run.intent_revised': '意图已修订',
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

function EvidenceField({ label, value }: { label: string; value: unknown }) {
  const rendered = displayTechnicalValue(value)
  if (!rendered) return null
  return <div><dt>{label}</dt><dd title={rendered}>{rendered}</dd></div>
}

function displayTechnicalValue(value: unknown): string | null {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) {
    const items = value.filter((item): item is string | number =>
      typeof item === 'string' || typeof item === 'number',
    )
    return items.length > 0 ? items.join(', ') : null
  }
  return null
}

function shortDigest(value: string): string {
  return value.length > 14 ? `${value.slice(0, 12)}…` : value
}

function evidenceLabel(value: string): string {
  return ({
    query_execution: '查询执行证据',
    capability_manifest: '产品能力清单',
    catalog_snapshot: '目录快照证据',
  } as Record<string, string>)[value] ?? value
}

function validationLabel(value: string): string {
  return ({
    evidence: '证据完整性',
    capability_scope: '能力范围',
    authorization_scope: '授权范围',
    sensitive_output: '敏感输出',
  } as Record<string, string>)[value] ?? value
}

function validationOutcome(value: string): string {
  return ({ passed: '通过', failed: '未通过', warning: '需关注' } as Record<string, string>)[value] ?? value
}

function displayIdentifier(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : '未冻结'
}

function displayRoute(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '未选择'
  return displayIdentifier((value as Record<string, unknown>).task_type)
}

function displayDefaults(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '无'
  const rendered = Object.values(value as Record<string, unknown>)
    .filter((item): item is string | number =>
      typeof item === 'string' || typeof item === 'number',
    )
    .map(String)
  return rendered.length > 0 ? rendered.join('、') : '无'
}
