import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { useAuth } from '../features/auth/context'
import { ApiError, apiClient } from '../lib/api/client'
import type { Invitation, Member, WorkspaceRole } from '../lib/api/types'

const schema = z.object({ email: z.email('请输入有效邮箱'), role: z.enum(['workspace_admin', 'data_admin', 'analyst', 'auditor', 'system_admin']) })
type Values = z.infer<typeof schema>
const labels: Record<WorkspaceRole, string> = { system_admin: '系统管理员', workspace_admin: '空间管理员', data_admin: '数据管理员', analyst: '分析用户', auditor: '审计员' }

export function MembersPage() {
  const { workspace } = useAuth(); const [members, setMembers] = useState<Member[]>([])
  const [error, setError] = useState<string | null>(null); const [inviteUrl, setInviteUrl] = useState<string | null>(null)
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { role: 'analyst' } })
  const canManage = workspace?.role === 'system_admin' || workspace?.role === 'workspace_admin'

  useEffect(() => {
    if (!workspace) return
    const path = `/api/v1/workspaces/${workspace.id}/members`
    void apiClient.request<Member[]>(path)
      .then(setMembers)
      .catch((reason: unknown) => setError(reason instanceof ApiError ? reason.message : '成员加载失败'))
  }, [workspace])

  const invite = handleSubmit(async (values) => {
    if (!workspace) return
    setError(null); setInviteUrl(null)
    try {
      const result = await apiClient.request<Invitation>(`/api/v1/workspaces/${workspace.id}/invitations`, { method: 'POST', body: JSON.stringify(values) })
      setInviteUrl(`${window.location.origin}/invite?token=${encodeURIComponent(result.invite_token)}`); reset({ email: '', role: 'analyst' })
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '邀请创建失败') }
  })

  async function updateRole(member: Member, role: WorkspaceRole) {
    if (!workspace) return
    const previous = member.role; setMembers((items) => items.map((item) => item.id === member.id ? { ...item, role } : item))
    try { await apiClient.request(`/api/v1/workspaces/${workspace.id}/members/${member.id}`, { method: 'PATCH', body: JSON.stringify({ role }) }) }
    catch (reason) { setMembers((items) => items.map((item) => item.id === member.id ? { ...item, role: previous } : item)); setError(reason instanceof ApiError ? reason.message : '角色更新失败') }
  }

  return <div className="page">
    <div className="page-heading"><div><p className="eyebrow">组织管理</p><h1>成员与权限</h1><p>管理{workspace?.name}的成员角色，最终权限由后端统一裁决。</p></div></div>
    {canManage && <form className="invite-bar" onSubmit={(event) => void invite(event)}><label><span>成员邮箱</span><input type="email" placeholder="name@company.com" {...register('email')} /></label><label><span>角色</span><select {...register('role')}>{Object.entries(labels).filter(([role]) => workspace?.role === 'system_admin' || role !== 'system_admin').map(([role, label]) => <option key={role} value={role}>{label}</option>)}</select></label><button className="primary-button" disabled={isSubmitting}>{isSubmitting ? '正在创建…' : '创建邀请'}</button>{errors.email && <small className="field-error">{errors.email.message}</small>}</form>}
    {inviteUrl && <div className="alert success" aria-live="polite"><strong>邀请已创建</strong><input readOnly value={inviteUrl} aria-label="邀请链接" /><button onClick={() => void navigator.clipboard.writeText(inviteUrl)}>复制链接</button></div>}
    {error && <div className="alert error" role="alert">{error}</div>}
    <section className="table-card"><table><thead><tr><th>成员</th><th>邮箱</th><th>角色</th><th>加入时间</th></tr></thead><tbody>{members.map((member) => <tr key={member.id}><td>{member.display_name}</td><td>{member.email}</td><td>{canManage ? <select aria-label={`调整${member.display_name}的角色`} value={member.role} onChange={(event) => void updateRole(member, event.target.value as WorkspaceRole)}>{Object.entries(labels).filter(([role]) => workspace?.role === 'system_admin' || role !== 'system_admin').map(([role, label]) => <option key={role} value={role}>{label}</option>)}</select> : labels[member.role]}</td><td>{new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(member.created_at))}</td></tr>)}</tbody></table>{members.length === 0 && !error && <p className="empty-state">暂无可显示成员。</p>}</section>
  </div>
}
