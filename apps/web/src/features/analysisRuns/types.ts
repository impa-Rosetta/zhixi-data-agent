export type AnalysisRunStatus =
  | 'queued'
  | 'running'
  | 'waiting_for_clarification'
  | 'waiting_for_confirmation'
  | 'completed'
  | 'failed_retryable'
  | 'failed'
  | 'cancelled'

export type AnalysisRun = {
  id: string
  workspace_id: string
  status: AnalysisRunStatus
  current_node: string
  context: Record<string, unknown>
  frozen_versions: Record<string, unknown>
  budget: Record<string, unknown>
  model_calls: number
  tool_calls: number
  total_tokens: number
  replan_count: number
  error_code: string | null
  version: number
  cancel_requested_at: string | null
  started_at: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

export type AnalysisRunSummary = {
  id: string
  status: AnalysisRunStatus
  current_node: string
  goal: string
  error_code: string | null
  model_calls: number
  tool_calls: number
  total_tokens: number
  created_at: string
  updated_at: string
  finished_at: string | null
}

export type AnalysisRunPage = {
  items: AnalysisRunSummary[]
  total: number
  limit: number
  offset: number
}

export type AnalysisMessage = {
  id: string
  role: string
  content: string
  context_patch: Record<string, unknown>
  created_at: string
}

export type AnalysisPlan = {
  id: string
  revision: number
  goal: string
  document: Record<string, unknown>
  requires_confirmation: boolean
  confirmed_at: string | null
  created_at: string
}

export type AnalysisStep = {
  id: string
  plan_id: string
  step_key: string
  tool_name: string
  arguments: Record<string, unknown>
  dependencies: string[]
  status: string
  error_code: string | null
  started_at: string | null
  finished_at: string | null
}

export type AnalysisToolCall = {
  id: string
  step_id: string
  tool_name: string
  tool_version: string
  argument_digest: string
  status: string
  result_summary: Record<string, unknown>
  error_code: string | null
  created_at: string
}

export type AnalysisArtifact = {
  id: string
  artifact_type: string
  summary: Record<string, unknown>
  content_digest: string
  created_at: string
}

export type AnalysisEvidence = {
  id: string
  artifact_id: string | null
  evidence_type: string
  reference: Record<string, unknown>
  evidence_digest: string
  created_at: string
}

export type AnalysisValidation = {
  id: string
  validation_type: string
  outcome: string
  findings: Array<Record<string, unknown>>
  created_at: string
}

export type AnalysisRunView = {
  run: AnalysisRun
  messages: AnalysisMessage[]
  plan: AnalysisPlan | null
  steps: AnalysisStep[]
  tool_calls: AnalysisToolCall[]
  artifacts: AnalysisArtifact[]
  evidence: AnalysisEvidence[]
  validations: AnalysisValidation[]
  last_event_sequence: number
}

export type AnalysisEvent = {
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}
