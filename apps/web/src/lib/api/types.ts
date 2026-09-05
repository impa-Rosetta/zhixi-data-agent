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
