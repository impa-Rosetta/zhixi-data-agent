import { createContext, useContext } from 'react'

import type { User, Workspace } from '../../lib/api/types'

export type Credentials = { email: string; password: string }
export type BootstrapInput = Credentials & {
  display_name: string
  workspace_name: string
  workspace_slug: string
}
export type InvitationInput = { invite_token: string; display_name: string; password: string }

export type AuthContextValue = {
  status: 'loading' | 'anonymous' | 'authenticated'
  user: User | null
  workspace: Workspace | null
  login(input: Credentials): Promise<void>
  bootstrap(input: BootstrapInput): Promise<void>
  acceptInvitation(input: InvitationInput): Promise<void>
  logout(): Promise<void>
  selectWorkspace(id: string): void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used within AuthProvider')
  return value
}
