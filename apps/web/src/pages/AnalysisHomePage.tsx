import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { AnalysisConversation } from '../features/analysisRuns/AnalysisConversation'
import { AnalysisInspector } from '../features/analysisRuns/AnalysisInspector'
import { AnalysisRunList } from '../features/analysisRuns/AnalysisRunList'
import {
  useAnalysisRunCommands,
  useAnalysisRuns,
} from '../features/analysisRuns/api'
import { useRealtimeAnalysisRun } from '../features/analysisRuns/useRealtimeAnalysisRun'
import { useAuth } from '../features/auth/context'
import { ApiError } from '../lib/api/client'
import './AnalysisHomePage.css'

type MobilePanel = 'runs' | 'conversation' | 'details'

export function AnalysisHomePage() {
  const { user, workspace } = useAuth()
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>('conversation')
  const [actionError, setActionError] = useState<string | null>(null)
  const canAnalyze = workspace?.role !== 'auditor'
  const workspaceId = canAnalyze ? workspace?.id : undefined
  const runs = useAnalysisRuns(workspaceId)
  const realtime = useRealtimeAnalysisRun(workspaceId, runId)
  const commands = useAnalysisRunCommands(workspaceId)
  const busy = [
    commands.create,
    commands.message,
    commands.confirmation,
    commands.cancel,
    commands.retry,
  ].some((command) => command.isPending)

  if (!canAnalyze) {
    return (
      <div className="analysis-permission-state">
        <span className="analysis-agent-mark">只读</span>
        <p className="eyebrow">{workspace?.name}</p>
        <h1>智能问析不可用于当前角色</h1>
        <p>审计员只能查看治理与审计信息，不能发起分析任务。</p>
      </div>
    )
  }

  const execute = async (operation: () => Promise<void>) => {
    setActionError(null)
    try {
      await operation()
    } catch (reason) {
      setActionError(
        reason instanceof ApiError || reason instanceof Error
          ? reason.message
          : '操作失败，请稍后重试。',
      )
    }
  }
  const newRun = () => {
    setActionError(null)
    setMobilePanel('conversation')
    void navigate('/app')
  }
  const selectRun = (id: string) => {
    setActionError(null)
    setMobilePanel('conversation')
    void navigate(`/app/analysis/${id}`)
  }

  return (
    <div className="analysis-page">
      <header className="analysis-page-heading">
        <div>
          <p className="eyebrow">{workspace?.name}</p>
          <h1>企业数据智能问析</h1>
          <p>Agent 通过已授权语义模型和工具执行真实分析。</p>
        </div>
        <div className="analysis-page-badges">
          <span><i />Policy Engine 已启用</span>
          <span>{roleLabel(workspace?.role)}</span>
        </div>
      </header>

      <nav className="analysis-mobile-tabs" aria-label="问析工作台视图">
        {([
          ['runs', '任务'],
          ['conversation', '问析'],
          ['details', '执行'],
        ] as const).map(([panel, label]) => (
          <button
            type="button"
            className={mobilePanel === panel ? 'active' : ''}
            aria-pressed={mobilePanel === panel}
            onClick={() => setMobilePanel(panel)}
            key={panel}
          >
            {label}
          </button>
        ))}
      </nav>

      <section className="analysis-workbench">
        <div className={mobilePanel === 'runs' ? 'mobile-visible' : ''}>
          <AnalysisRunList
            items={runs.data?.items ?? []}
            selectedId={runId}
            loading={runs.isLoading}
            onSelect={selectRun}
            onNew={newRun}
          />
        </div>
        <div className={mobilePanel === 'conversation' ? 'mobile-visible' : ''}>
          {runId && realtime.isLoading ? (
            <div className="analysis-loading"><span className="spinner" />正在恢复任务…</div>
          ) : (
            <AnalysisConversation
              view={realtime.data}
              userName={user?.display_name}
              busy={busy}
              actionError={actionError}
              onCreate={(message) =>
                execute(async () => {
                  const run = await commands.create.mutateAsync({
                    message,
                    idempotencyKey: newIdempotencyKey(),
                  })
                  selectRun(run.id)
                })
              }
              onMessage={(message) =>
                execute(async () => {
                  if (!runId) return
                  await commands.message.mutateAsync({
                    runId,
                    message,
                    idempotencyKey: newIdempotencyKey(),
                  })
                })
              }
              onConfirm={(approved) =>
                execute(async () => {
                  if (!runId) return
                  await commands.confirmation.mutateAsync({ runId, approved })
                })
              }
              onCancel={() =>
                execute(async () => {
                  if (runId) await commands.cancel.mutateAsync(runId)
                })
              }
              onRetry={() =>
                execute(async () => {
                  if (runId) await commands.retry.mutateAsync(runId)
                })
              }
              onNew={newRun}
            />
          )}
        </div>
        <div className={mobilePanel === 'details' ? 'mobile-visible' : ''}>
          <AnalysisInspector
            view={realtime.data}
            events={realtime.events}
            connection={realtime.connection}
            streamError={realtime.streamError}
          />
        </div>
      </section>
    </div>
  )
}

function newIdempotencyKey(): string {
  return typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function roleLabel(role?: string): string {
  return ({
    system_admin: '系统管理员',
    workspace_admin: '空间管理员',
    data_admin: '数据管理员',
    analyst: '分析用户',
    auditor: '审计员',
  } as Record<string, string>)[role ?? ''] ?? '成员'
}
