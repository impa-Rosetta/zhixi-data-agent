import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'

import { ApiError } from '../../lib/api/client'
import type { DataSourceCreateInput, DataSourceCreateResult } from '../../lib/api/types'
import { useCreateDataSource } from './api'

const schema = z.object({
  name: z.string().trim().min(1, '请输入数据源名称').max(120),
  description: z.string().trim().max(2_000, '说明不能超过2000字'),
  source_type: z.enum(['postgresql', 'mysql']),
  host: z.string().trim().min(1, '请输入主机名').max(253),
  port: z.number().int().min(1, '端口范围为1到65535').max(65_535, '端口范围为1到65535'),
  database_name: z.string().trim().min(1, '请输入数据库名').max(128),
  username: z.string().trim().min(1, '请输入只读账号').max(128),
  password: z.string().min(1, '请输入密码').max(1_024),
  tls_mode: z.enum(['disable', 'prefer', 'require', 'verify_ca', 'verify_full']),
  tls_ca_certificate: z.string().max(64_000, 'CA证书内容过长'),
}).superRefine((value, context) => {
  if ((value.tls_mode === 'verify_ca' || value.tls_mode === 'verify_full') && !value.tls_ca_certificate.trim()) {
    context.addIssue({ code: 'custom', path: ['tls_ca_certificate'], message: '此TLS模式必须提供CA证书' })
  }
})

type Values = z.infer<typeof schema>
type Props = {
  workspaceId: string
  onClose: () => void
  onCreated: (result: DataSourceCreateResult) => void
}

const stepFields: Record<number, (keyof Values)[]> = {
  1: ['name', 'description', 'source_type'],
  2: ['host', 'port', 'database_name', 'username', 'password', 'tls_mode', 'tls_ca_certificate'],
  3: [],
}

export function DataSourceWizard({ workspaceId, onClose, onCreated }: Props) {
  const [step, setStep] = useState(1)
  const mutation = useCreateDataSource(workspaceId)
  const { register, handleSubmit, trigger, getValues, setValue, control, formState: { errors } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '', description: '', source_type: 'postgresql', host: '', port: 5432,
      database_name: '', username: '', password: '', tls_mode: 'require', tls_ca_certificate: '',
    },
  })
  const sourceType = useWatch({ control, name: 'source_type' })
  const tlsMode = useWatch({ control, name: 'tls_mode' })

  useEffect(() => {
    setValue('port', sourceType === 'postgresql' ? 5432 : 3306)
  }, [setValue, sourceType])

  async function next() {
    if (await trigger(stepFields[step])) setStep((current) => Math.min(3, current + 1))
  }

  const submit = handleSubmit(async (values) => {
    const payload: DataSourceCreateInput = {
      name: values.name,
      description: values.description || null,
      source_type: values.source_type,
      host: values.host,
      port: values.port,
      database_name: values.database_name,
      tls_mode: values.tls_mode,
      credentials: {
        username: values.username,
        password: values.password,
        tls_ca_certificate: values.tls_ca_certificate.trim() || null,
      },
    }
    try {
      onCreated(await mutation.mutateAsync(payload))
    } finally {
      setValue('password', '')
    }
  })
  const values = getValues()
  const error = mutation.error instanceof ApiError ? mutation.error.message : mutation.error?.message

  return <div className="modal-backdrop" role="presentation">
    <section className="wizard" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
      <header className="wizard-header">
        <div><p className="eyebrow">安全接入向导</p><h2 id="wizard-title">添加企业数据源</h2></div>
        <button className="icon-button" type="button" aria-label="关闭" onClick={onClose} disabled={mutation.isPending}>×</button>
      </header>
      <ol className="stepper" aria-label="接入步骤">
        {['基本信息', '连接与安全', '确认并检测'].map((label, index) => <li key={label} className={step === index + 1 ? 'active' : step > index + 1 ? 'done' : ''}><span>{index + 1}</span>{label}</li>)}
      </ol>
      <form onSubmit={(event) => void submit(event)}>
        <div className="wizard-body">
          {step === 1 && <div className="form-stack compact">
            <label className="field"><span>数据源名称</span><input autoFocus placeholder="例如：生产制造主库" {...register('name')} />{errors.name && <small className="field-error">{errors.name.message}</small>}</label>
            <label className="field"><span>数据库类型</span><select {...register('source_type')}><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option></select></label>
            <label className="field"><span>用途说明（可选）</span><textarea rows={3} placeholder="说明数据范围与业务用途" {...register('description')} />{errors.description && <small className="field-error">{errors.description.message}</small>}</label>
          </div>}
          {step === 2 && <div className="form-stack compact">
            <div className="form-grid"><label className="field"><span>主机名</span><input autoFocus placeholder="db.company.internal" {...register('host')} />{errors.host && <small className="field-error">{errors.host.message}</small>}</label><label className="field"><span>端口</span><input type="number" {...register('port', { valueAsNumber: true })} />{errors.port && <small className="field-error">{errors.port.message}</small>}</label></div>
            <label className="field"><span>数据库名</span><input placeholder="database" {...register('database_name')} />{errors.database_name && <small className="field-error">{errors.database_name.message}</small>}</label>
            <div className="form-grid"><label className="field"><span>只读账号</span><input autoComplete="off" {...register('username')} />{errors.username && <small className="field-error">{errors.username.message}</small>}</label><label className="field"><span>密码</span><input type="password" autoComplete="new-password" {...register('password')} />{errors.password && <small className="field-error">{errors.password.message}</small>}</label></div>
            <label className="field"><span>TLS策略</span><select {...register('tls_mode')}><option value="require">要求加密</option><option value="verify_full">校验证书与主机</option><option value="verify_ca">校验证书</option><option value="prefer">优先加密</option><option value="disable">关闭（仅限受控内网）</option></select></label>
            {(tlsMode === 'verify_ca' || tlsMode === 'verify_full') && <label className="field"><span>CA证书（PEM）</span><textarea rows={4} {...register('tls_ca_certificate')} />{errors.tls_ca_certificate && <small className="field-error">{errors.tls_ca_certificate.message}</small>}</label>}
            {tlsMode === 'disable' && <div className="security-warning">关闭TLS会让传输失去加密保护，仅可用于经过批准的隔离内网。</div>}
          </div>}
          {step === 3 && <div className="review-panel">
            <div><span>数据源</span><strong>{values.name}</strong></div><div><span>类型</span><strong>{values.source_type === 'postgresql' ? 'PostgreSQL' : 'MySQL'}</strong></div>
            <div><span>地址</span><strong>{values.host}:{values.port}</strong></div><div><span>数据库</span><strong>{values.database_name}</strong></div>
            <div><span>连接账号</span><strong>{values.username}</strong></div><div><span>TLS</span><strong>{values.tls_mode}</strong></div>
            <p>创建后系统立即执行真实的网络策略、只读权限和连接测试。密码只会加密发送，不会在页面中保存或回显。</p>
          </div>}
          {error && <div className="alert error" role="alert">{error}</div>}
        </div>
        <footer className="wizard-footer"><button type="button" className="secondary-button" onClick={step === 1 ? onClose : () => setStep((current) => current - 1)} disabled={mutation.isPending}>{step === 1 ? '取消' : '上一步'}</button>{step < 3 ? <button type="button" className="primary-button" onClick={() => void next()}>下一步</button> : <button className="primary-button" disabled={mutation.isPending}>{mutation.isPending ? '正在安全创建…' : '创建并开始检测'}</button>}</footer>
      </form>
    </section>
  </div>
}
