export type WorkspaceRole =
  | 'system_admin'
  | 'workspace_admin'
  | 'data_admin'
  | 'analyst'
  | 'auditor'

export type TokenResponse = {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export type Workspace = {
  id: string
  name: string
  slug: string
  role: WorkspaceRole
}

export type User = {
  id: string
  email: string
  display_name: string
  is_active: boolean
  workspaces: Workspace[]
}

export type Member = {
  id: string
  user_id: string
  email: string
  display_name: string
  role: WorkspaceRole
  created_at: string
}

export type Invitation = {
  id: string
  email: string
  role: WorkspaceRole
  expires_at: string
  invite_token: string
}

export type DataSourceType = 'postgresql' | 'mysql'
export type DataSourceStatus = 'draft' | 'testing' | 'ready' | 'degraded' | 'disabled' | 'deleted'
export type TlsMode = 'disable' | 'prefer' | 'require' | 'verify_ca' | 'verify_full'
export type ScanJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type ScanJobType = 'connection_test' | 'metadata_scan' | 'profile_scan'

export type DataSource = {
  id: string
  workspace_id: string
  name: string
  description: string | null
  source_type: DataSourceType
  host: string
  port: number
  database_name: string
  tls_mode: TlsMode
  network_policy_id: string | null
  status: DataSourceStatus
  health_code: string | null
  active_snapshot_id: string | null
  version: number
  last_checked_at: string | null
  last_success_at: string | null
  created_at: string
  updated_at: string
}

export type ScanJob = {
  id: string
  data_source_id: string
  snapshot_id: string | null
  parent_job_id: string | null
  retry_of_job_id: string | null
  job_type: ScanJobType
  trigger: 'initial' | 'manual' | 'scheduled'
  status: ScanJobStatus
  phase: string | null
  progress: number
  error_code: string | null
  created_at: string
  started_at: string | null
  heartbeat_at: string | null
  cancel_requested_at: string | null
  finished_at: string | null
}

export type DataSourcePage = { items: DataSource[]; total: number; limit: number; offset: number }

export type DataSourceCreateInput = {
  name: string
  description: string | null
  source_type: DataSourceType
  host: string
  port: number
  database_name: string
  tls_mode: TlsMode
  credentials: { username: string; password: string; tls_ca_certificate: string | null }
}

export type DataSourceCreateResult = { data_source: DataSource; job: ScanJob }
export type CatalogSnapshot = {
  id: string
  data_source_id: string
  version: number
  status: 'building' | 'published' | 'rejected'
  database_product: string
  database_version: string | null
  scan_options: Record<string, unknown>
  object_counts: Record<string, unknown>
  content_digest: string | null
  sampling_enabled: boolean
  profiling_status: 'disabled' | 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  profiling_error_code: string | null
  profiling_options: Record<string, unknown>
  profile_counts: Record<string, unknown>
  profiling_started_at: string | null
  profiling_finished_at: string | null
  started_at: string
  completed_at: string | null
}
export type CatalogColumn = {
  name: string
  ordinal_position: number
  data_type: string
  native_type: string
  nullable: boolean
  default_expression: string | null
  comment: string | null
}

export type CatalogConstraint = {
  name: string
  constraint_type: string
  columns: string[]
  referenced_schema: string | null
  referenced_relation: string | null
  referenced_columns: string[]
}

export type CatalogIndex = {
  name: string
  columns: string[]
  unique: boolean
  method: string | null
  predicate: string | null
}

export type CatalogRelation = {
  name: string
  relation_type: string
  comment: string | null
  columns: CatalogColumn[]
  constraints: CatalogConstraint[]
  indexes: CatalogIndex[]
}

export type CatalogSchema = {
  name: string
  comment: string | null
  relations: CatalogRelation[]
}

export type Catalog = {
  snapshot: CatalogSnapshot
  schemas: CatalogSchema[]
}
export type CatalogDiff = {
  id: string
  from_snapshot_id: string | null
  to_snapshot_id: string
  change_type: string
  object_type: string
  object_key: string
  severity: string
  before_value: Record<string, unknown> | null
  after_value: Record<string, unknown> | null
}

export type CatalogDiffPage = {
  items: CatalogDiff[]
  total: number
  limit: number
  offset: number
}
export type CatalogSample = {
  ordinal: number
  masked_value: string
  value_type: string
  byte_count: number
}

export type CatalogColumnProfile = {
  id: string
  column_id: string
  schema_name: string
  relation_name: string
  column_name: string
  data_type: string
  native_type: string
  sample_row_count: number
  non_null_count: number
  estimated_row_count: number | null
  sample_null_rate: number | null
  sampled_distinct_count: number | null
  minimum_value: string | null
  maximum_value: string | null
  minimum_length: number | null
  maximum_length: number | null
  average_length: number | null
  sensitivity_type: string | null
  sensitivity_confidence: number
  sensitivity_reasons: string[]
  metric_sources: Record<string, string>
  samples: CatalogSample[]
}

export type CatalogProfileList = {
  snapshot_id: string
  profiling_status: CatalogSnapshot['profiling_status']
  profiling_error_code: string | null
  profile_counts: Record<string, unknown>
  items: CatalogColumnProfile[]
}
export type SamplingTableScope = { schema_name: string; table_name: string }
export type SamplingPolicy = {
  data_source_id: string
  enabled: boolean
  schema_allowlist: string[]
  table_allowlist: SamplingTableScope[]
  max_rows_per_table: number
  max_values_per_column: number
  max_value_chars: number
  max_bytes_per_table: number
  max_bytes_per_job: number
  statement_timeout_seconds: number
  version: number
  updated_at: string | null
}
export type SamplingPolicyInput = Omit<SamplingPolicy, 'data_source_id' | 'updated_at'>

export type ScanSchedule = {
  data_source_id: string
  enabled: boolean
  frequency: 'daily' | 'weekly'
  timezone: string
  local_time: string
  day_of_week: number | null
  next_run_at: string | null
  last_enqueued_at: string | null
  version: number
  updated_at: string | null
}
export type ScanScheduleInput = Pick<ScanSchedule, 'enabled' | 'frequency' | 'timezone' | 'local_time' | 'day_of_week' | 'version'>
