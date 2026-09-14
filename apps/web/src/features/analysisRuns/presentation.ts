import type { AnalysisRunStatus } from './types'

export const runStatusLabel: Record<AnalysisRunStatus, string> = {
  queued: '等待执行',
  running: '执行中',
  waiting_for_clarification: '等待你的回答',
  waiting_for_confirmation: '等待确认',
  completed: '已完成',
  failed_retryable: '可以重试',
  failed: '暂未完成',
  cancelled: '已取消',
}

const nodeLabels: Record<string, string> = {
  understand: '理解问题',
  bind: '绑定语义',
  plan: '制定计划',
  policy_check: '策略检查',
  execute: '执行工具',
  verify: '验证结果',
  present: '整理结果',
  cancelled: '任务取消',
}

const errorLabels: Record<string, string> = {
  'model.not_configured': '当前部署尚未配置模型服务，可在配置完成后重试。',
  'model.rate_limited': '模型服务当前限流，请稍后重试。',
  'model.timeout': '模型响应超时，已保留现有进度。',
  'agent.execution_failed': '这次分析没有完成，也没有产生可用结论。你可以调整问题后重新发起分析。',
  'agent.model_budget_exhausted': '本次运行已达到模型调用预算。',
  'agent.tool_budget_exhausted': '本次运行已达到工具调用预算。',
}

export function nodeLabel(node: string): string {
  return nodeLabels[node] ?? node
}

export function errorLabel(code: string | null): string | null {
  if (!code) return null
  return errorLabels[code] ?? '这次分析没有完成。你可以调整问题后重新发起分析；技术详情中保留了诊断信息。'
}

export function formatRunTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
