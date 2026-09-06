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
