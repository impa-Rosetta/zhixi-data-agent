import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '../components/auth/AuthLayout'
import { Field } from '../components/auth/Field'
import { useAuth } from '../features/auth/context'
import { ApiError, apiClient } from '../lib/api/client'

const schema = z.object({
  email: z.email('请输入有效邮箱'), display_name: z.string().min(1, '请输入姓名'),
  password: z.string().min(12, '密码至少12位'), workspace_name: z.string().min(1, '请输入工作空间名称'),
  workspace_slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$/, '使用3–80位小写字母、数字或连字符'),
})
type Values = z.infer<typeof schema>

export function SetupPage() {
  const auth = useAuth(); const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [allowed, setAllowed] = useState<boolean | null>(null)
  const { register, handleSubmit, setValue, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) })
  useEffect(() => { apiClient.request<{ initialized: boolean }>('/api/v1/auth/bootstrap-status', {}, false).then((x) => setAllowed(!x.initialized)).catch((x: unknown) => setError(x instanceof ApiError ? x.message : '服务不可用')) }, [])
  if (auth.status === 'authenticated') return <Navigate to="/app" replace />
  if (allowed === false) return <Navigate to="/login" replace />

  const submit = handleSubmit(async (values) => {
    setError(null)
    try { await auth.bootstrap(values); void navigate('/app', { replace: true }) }
    catch (reason) {
      const message = reason instanceof ApiError ? reason.message : '初始化失败'; setError(message)
      if (reason instanceof ApiError && reason.status === 409) setTimeout(() => { void navigate('/login', { replace: true }) }, 1200)
    }
  })
  return <AuthLayout eyebrow="首次初始化" title="创建安全管理入口" subtitle="建立首个管理员和工作空间，此操作只能完成一次。">
    <form className="form-stack" onSubmit={(event) => void submit(event)} noValidate>
      <div className="form-grid"><Field label="管理员姓名" autoComplete="name" {...register('display_name')} error={errors.display_name?.message} /><Field label="管理员邮箱" type="email" autoComplete="email" {...register('email')} error={errors.email?.message} /></div>
      <Field label="工作空间名称" {...register('workspace_name')} onBlur={(event) => setValue('workspace_slug', slugify(event.target.value), { shouldValidate: true })} error={errors.workspace_name?.message} />
      <Field label="工作空间标识" placeholder="demo-factory" {...register('workspace_slug')} error={errors.workspace_slug?.message} />
      <Field label="管理员密码" type="password" autoComplete="new-password" {...register('password')} error={errors.password?.message} />
      {error && <div className="alert error" role="alert">{error}</div>}
      <button className="primary-button" disabled={isSubmitting || allowed !== true}>{isSubmitting ? '正在创建…' : allowed === null ? '正在检查平台…' : '创建并进入工作台'}</button>
    </form>
  </AuthLayout>
}

function slugify(value: string): string {
  const latin = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return latin.length >= 3 ? latin : `workspace-${Date.now().toString().slice(-6)}`
}
