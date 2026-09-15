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

export type AnalysisConversationStatus = 'active' | 'archived'
export type AnalysisTurnStatus =
  | 'queued'
  | 'running'
  | 'waiting_for_user'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type AnalysisConversation = {
  id: string
  workspace_id: string
  title: string
  status: AnalysisConversationStatus
  context: Record<string, unknown>
  active_turn_id: string | null
  last_turn_sequence: number
  version: number
  created_at: string
  updated_at: string
  archived_at: string | null
}

export type AnalysisConversationSummary = {
  id: string
  title: string
  status: AnalysisConversationStatus
  active_turn_id: string | null
  active_turn_status: AnalysisTurnStatus | null
  last_turn_sequence: number
  last_message_preview: string | null
  created_at: string
  updated_at: string
}

export type AnalysisConversationPage = {
  items: AnalysisConversationSummary[]
  total: number
  limit: number
  offset: number
}

export type AnalysisTurn = {
  id: string
  sequence: number
  parent_turn_id: string | null
  analysis_run_id: string | null
  relation: 'initial' | 'continue' | 'refine' | 'explain' | 'compare' | 'switch_topic'
  status: AnalysisTurnStatus
  queued_at: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export type AnalysisConversationTurnView = {
  turn: AnalysisTurn
  analysis: AnalysisRunView
}

export type AnalysisConversationView = {
  conversation: AnalysisConversation
  turns: AnalysisConversationTurnView[]
  total_turns: number
  limit: number
  offset: number
  read_only: boolean
  legacy_run_id: string | null
}
