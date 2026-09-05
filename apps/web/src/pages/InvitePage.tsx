import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '../components/auth/AuthLayout'
import { Field } from '../components/auth/Field'
import { useAuth } from '../features/auth/context'
import { ApiError } from '../lib/api/client'

const schema = z.object({ display_name: z.string().min(1, '请输入姓名'), password: z.string().min(12, '密码至少12位') })
type Values = z.infer<typeof schema>

export function InvitePage() {
  const auth = useAuth(); const navigate = useNavigate(); const [params] = useSearchParams()
  const token = params.get('token'); const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) })
  if (auth.status === 'authenticated') return <Navigate to="/app" replace />
  const submit = handleSubmit(async (values) => {
    if (!token) return
    try { await auth.acceptInvitation({ invite_token: token, ...values }); void navigate('/app', { replace: true }) }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '接受邀请失败') }
  })
  return <AuthLayout eyebrow="工作空间邀请" title="完成账号设置" subtitle="设置姓名和安全密码后即可加入受邀工作空间。">
    {!token ? <div className="alert error" role="alert">邀请链接缺少令牌，请联系管理员重新发送。</div> : <form className="form-stack" onSubmit={(event) => void submit(event)} noValidate>
      <Field label="姓名" autoComplete="name" {...register('display_name')} error={errors.display_name?.message} />
      <Field label="密码" type="password" autoComplete="new-password" {...register('password')} error={errors.password?.message} />
      {error && <div className="alert error" role="alert">{error}</div>}
      <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? '正在加入…' : '加入工作空间'}</button>
    </form>}
  </AuthLayout>
}
