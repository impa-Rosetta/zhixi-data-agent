import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '../components/auth/AuthLayout'
import { Field } from '../components/auth/Field'
import { useAuth } from '../features/auth/context'
import { ApiError } from '../lib/api/client'

const schema = z.object({ email: z.email('请输入有效邮箱'), password: z.string().min(1, '请输入密码') })
type Values = z.infer<typeof schema>

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) })
  if (auth.status === 'authenticated') return <Navigate to="/app" replace />

  const submit = handleSubmit(async (values) => {
    setError(null)
    try { await auth.login(values); void navigate('/app', { replace: true }) }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '登录失败') }
  })
  return <AuthLayout eyebrow="安全登录" title="欢迎回来" subtitle="使用你的企业账号进入工作空间。">
    <form className="form-stack" onSubmit={(event) => void submit(event)} noValidate>
      <Field label="邮箱" type="email" autoComplete="email" {...register('email')} error={errors.email?.message} />
      <Field label="密码" type="password" autoComplete="current-password" {...register('password')} error={errors.password?.message} />
      {error && <div className="alert error" role="alert">{error}</div>}
      <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? '正在登录…' : '登录'}</button>
    </form>
  </AuthLayout>
}
