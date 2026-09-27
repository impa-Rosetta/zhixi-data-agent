import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useAuth } from '../features/auth/context'
import {
  useEvaluationCases, useEvaluationCommands, useEvaluationDetail,
  useEvaluationRuns, useEvaluationSuites,
} from '../features/evaluations/api'
import './EvaluationsPage.css'

const categories: Record<string, string> = {
  standard: '标准问题', multi_turn: '多轮交互', ambiguity: '歧义澄清', anomaly: '异常数据', security: '安全场景',
}
const states: Record<string, string> = {
  queued: '等待执行', running: '正在执行', completed: '已完成', partial: '部分完成',
  cancelled: '已取消', passed: '通过', failed: '失败', infra_error: '环境故障', blocked: '未执行',
}
function percent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '尚无结果'
}

export function EvaluationsPage() {
  const { workspace } = useAuth()
  const [search, setSearch] = useSearchParams()
  const canRead = ['system_admin', 'workspace_admin', 'auditor'].includes(workspace?.role ?? '')
  const workspaceId = canRead ? workspace?.id : undefined
  const suites = useEvaluationSuites(workspaceId)
  const runs = useEvaluationRuns(workspaceId)
  const runId = search.get('run') ?? runs.data?.items[0]?.id
  const detail = useEvaluationDetail(workspaceId, runId)
  const running = detail.data?.status === 'running' || detail.data?.status === 'queued'
  const cases = useEvaluationCases(workspaceId, runId, running)
  const command = useEvaluationCommands(workspaceId)
  const [category, setCategory] = useState('all')
  const [caseState, setCaseState] = useState('all')
  const [version, setVersion] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const currentSuite = suites.data?.items.find((item) => item.suite_version === version) ?? suites.data?.items[0]
  const run = detail.data
  const canManage = suites.data?.can_manage === true
  const filtered = cases.data?.items.filter((item) => (category === 'all' || item.category === category)
    && (caseState === 'all' || item.status === caseState)) ?? []

  async function create() {
    if (!currentSuite || !confirm) return
    setError(null)
    try {
      const created = await command.mutateAsync({ action: 'create', version: currentSuite.suite_version, idempotencyKey: crypto.randomUUID() })
      if (created) setSearch({ run: created.id })
      setConfirm(false)
    } catch { setError('评测未能启动，请检查权限与隔离环境后重试。') }
  }

  async function change(action: 'cancel' | 'resume') {
    if (!runId) return
    setError(null)
    try { await command.mutateAsync({ action, runId }) }
    catch { setError('运行状态或权限已变化，请刷新后重试。') }
  }

  if (!canRead) return <div className="page"><h1>评测中心</h1><p role="alert">当前角色没有评测访问权限，请联系管理员。</p></div>
  return <div className="page evaluation-page">
    <div className="page-heading"><div><p className="eyebrow">质量与安全回归</p><h1>评测中心</h1><p>区分离线回归和真实模型基准；未执行、环境故障不会算作通过。</p></div></div>
    <section className="evaluation-panel" aria-label="案例集与执行环境">
      <h2>版本化案例集</h2>
      {suites.isLoading && <p>正在加载案例集…</p>}
      {suites.isError && <p role="alert">无法读取案例集，请检查权限后重试。</p>}
      {currentSuite && <>
        <label>案例集版本<select value={currentSuite.suite_version} onChange={(event) => setVersion(event.target.value)}>{suites.data?.items.map((item) => <option key={item.suite_version}>{item.suite_version}</option>)}</select></label>
        <p>{currentSuite.published ? '正式案例集' : '未发布草案，仍需人工审阅'} · {currentSuite.case_count} 个场景</p>
        <div className="evaluation-tags">{Object.entries(currentSuite.category_counts).map(([key, count]) => <span key={key}>{categories[key] ?? key} {count}</span>)}</div>
        <p className="evaluation-note">离线轨道使用固定模型响应与合成数据，结果不是 DeepSeek 实测准确率。真实模型批量运行暂未开放。</p>
        {canManage && <div className="evaluation-create">
          <label><input type="checkbox" checked={confirm} onChange={(event) => setConfirm(event.target.checked)} />我确认在隔离合成环境执行离线评测，上限 300 秒，不调用付费模型。</label>
          <button className="primary-button" disabled={!confirm || !suites.data?.offline_enabled || command.isPending} onClick={() => void create()}>{command.isPending ? '正在提交…' : '运行离线评测'}</button>
          {!suites.data?.offline_enabled && <p>隔离执行环境尚未启用，不能启动评测。</p>}
        </div>}
      </>}
    </section>
    {error && <p className="alert error" role="alert">{error}</p>}
    <section className="evaluation-panel" aria-label="评测运行记录">
      <h2>运行记录</h2>
      {runs.isError && <p role="alert">无法读取运行记录。</p>}
      {!runs.isLoading && runs.data?.items.length === 0 && <p>还没有运行记录。系统不会展示模拟通过率。</p>}
      <div className="evaluation-run-list">{runs.data?.items.map((item) => <button key={item.id} className={item.id === runId ? 'active' : ''} onClick={() => setSearch({ run: item.id })}>v{item.suite_version} · {item.track === 'offline' ? '离线回归' : '真实模型'} · {states[item.status]}<small>{new Date(item.created_at).toLocaleString('zh-CN')}</small></button>)}</div>
    </section>
    {detail.isError && <p role="alert">运行不存在或当前账号无权访问，请重新选择运行。</p>}
    {run && <section className="evaluation-panel" aria-label="评测运行详情">
      <header className="evaluation-detail-heading"><h2>运行详情</h2><span aria-live="polite">{states[run.status]}</span>
        {canManage && running && <button disabled={command.isPending} onClick={() => void change('cancel')}>取消运行</button>}
        {canManage && run.status === 'partial' && run.error_code === 'evaluation.worker_lost' && <button disabled={command.isPending} onClick={() => void change('resume')}>继续未完成案例</button>}
      </header>
      <p>轨道：{run.track === 'offline' ? '离线回归（固定模型响应）' : '真实模型基准'} · 模型：{run.model_version}</p>
      <p className="evaluation-digest">案例集摘要：{run.suite_digest}</p>
      <div className="evaluation-metrics">
        <div><span>全案例覆盖率</span><strong>{percent(run.summary.coverage_rate)}</strong></div>
        <div><span>已评估通过率</span><strong>{percent(run.summary.evaluated_pass_rate)}</strong></div>
        <div><span>全案例通过率</span><strong>{percent(run.summary.all_case_pass_rate)}</strong></div>
      </div>
      {Array.isArray(run.summary.safety_failure_ids) && run.summary.safety_failure_ids.length > 0 && <p role="alert" className="alert error">存在安全案例失败，不能用平均分掩盖，必须先处理。</p>}
      <p>已记录模型调用 {run.calls_used} 次 · token {run.tokens_used} · 执行尝试 {run.attempt_count} 次</p>
      {run.error_code && <p role="status">{run.error_code === 'evaluation.worker_lost' ? '后台执行中断，已保留完成结果。' : '本次运行未能完整执行，请检查失败案例和隔离环境。'}</p>}
      <div className="evaluation-filters"><label>场景类别<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">全部类别</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>案例状态<select value={caseState} onChange={(event) => setCaseState(event.target.value)}><option value="all">全部状态</option>{['queued', 'running', 'passed', 'failed', 'infra_error', 'blocked'].map((key) => <option key={key} value={key}>{states[key]}</option>)}</select></label></div>
      {cases.isError && <p role="alert">案例结果暂时无法读取。</p>}
      <div className="evaluation-table"><table><thead><tr><th>案例</th><th>类别</th><th>状态</th><th>检查与耗时</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.case_id}><td>{item.case_id}</td><td>{categories[item.category]}</td><td>{states[item.status]}</td><td>{item.assertion_results.filter((check) => check.passed).length}/{item.assertion_results.length} 项 · {item.duration_ms} ms{item.assertion_results.some((check) => !check.passed) && <details><summary>查看失败断言</summary>{item.assertion_results.filter((check) => !check.passed).map((check) => <p key={check.name}>{check.name}</p>)}</details>}</td></tr>)}</tbody></table></div>
      {cases.data && cases.data.total > cases.data.items.length && <p>当前仅显示前 {cases.data.items.length} 条；总计 {cases.data.total} 条，未加载案例不计为通过。</p>}
    </section>}
  </div>
}
