import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { AnalysisInspector } from '../features/analysisRuns/AnalysisInspector'
import { ContinuousConversation } from '../features/analysisRuns/ContinuousConversation'
import { ConversationList } from '../features/analysisRuns/ConversationList'
import {
  useAnalysisConversationCommands,
  useAnalysisConversations,
} from '../features/analysisRuns/conversationApi'
import { useRealtimeAnalysisConversation } from '../features/analysisRuns/useRealtimeAnalysisConversation'
import { useAuth } from '../features/auth/context'
import { ApiError } from '../lib/api/client'
import './AnalysisHomePage.css'

type MobilePanel = 'conversations' | 'conversation' | 'details'

export function ConversationWorkspacePage() {
  const { user, workspace } = useAuth()
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>('conversation')
  const [error, setError] = useState<string | null>(null)
  const canAnalyze = workspace?.role !== 'auditor'
  const workspaceId = canAnalyze ? workspace?.id : undefined
  const conversations = useAnalysisConversations(workspaceId)
  const view = useRealtimeAnalysisConversation(workspaceId, conversationId)
  const commands = useAnalysisConversationCommands(workspaceId)
  const latest = view.data?.turns.at(-1)?.analysis

  if (!canAnalyze) {
    return (
      <div className="analysis-permission-state">
        <span className="analysis-agent-mark">只读</span>
        <h1>当前角色不能发起智能问析</h1>
        <p>你仍可在治理和审计页面查看授权范围内的信息。</p>
      </div>
    )
  }

  const submit = async (message: string, suggestionId?: string): Promise<void> => {
    setError(null)
    try {
      if (conversationId) {
        await commands.message.mutateAsync({
          conversationId,
          message,
          idempotencyKey: newIdempotencyKey(),
          suggestionId,
        })
      } else {
        const conversation = await commands.create.mutateAsync({
          message,
          idempotencyKey: newIdempotencyKey(),
        })
        await navigate(`/app/conversations/${conversation.id}`)
      }
    } catch (reason) {
      setError(
        reason instanceof ApiError || reason instanceof Error
          ? reason.message
          : '消息发送失败，请稍后重试。',
      )
      throw reason
    }
  }

  const cancel = async (turnId: string): Promise<void> => {
    if (!conversationId) return
    setError(null)
    try {
      await commands.cancel.mutateAsync({ conversationId, turnId })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '取消失败，请稍后重试。')
      throw reason
    }
  }

  const selectConversation = (id: string) => {
    setError(null)
    setMobilePanel('conversation')
    void navigate(`/app/conversations/${id}`)
  }

  return (
    <div className="analysis-page">
      <header className="analysis-page-heading">
        <div>
          <p className="eyebrow">{workspace?.name}</p>
          <h1>企业数据智能问析</h1>
          <p>像与分析师交谈一样持续追问，每一轮仍保持独立证据链。</p>
        </div>
        <div className="analysis-page-badges"><span><i />多轮会话已启用</span></div>
      </header>
      <nav className="analysis-mobile-tabs" aria-label="问析工作台视图">
        {([
          ['conversations', '会话'],
          ['conversation', '问析'],
          ['details', '执行'],
        ] as const).map(([panel, label]) => (
          <button
            type="button"
            className={mobilePanel === panel ? 'active' : ''}
            aria-pressed={mobilePanel === panel}
            onClick={() => setMobilePanel(panel)}
            key={panel}
          >{label}</button>
        ))}
      </nav>
      <section className="analysis-workbench">
        <div className={mobilePanel === 'conversations' ? 'mobile-visible' : ''}>
          <ConversationList
            items={conversations.data?.items ?? []}
            selectedId={conversationId}
            loading={conversations.isLoading}
            onSelect={selectConversation}
            onNew={() => void navigate('/app')}
          />
        </div>
        <div className={mobilePanel === 'conversation' ? 'mobile-visible' : ''}>
          {conversationId && view.isLoading ? (
            <div className="analysis-loading"><span className="spinner" />正在恢复会话…</div>
          ) : (
            <ContinuousConversation
              view={view.data}
              userName={user?.display_name}
              busy={commands.create.isPending || commands.message.isPending || commands.cancel.isPending}
              error={error}
              onSubmit={submit}
              onCancel={cancel}
            />
          )}
        </div>
        <div className={mobilePanel === 'details' ? 'mobile-visible' : ''}>
          <AnalysisInspector
            view={latest}
            events={[]}
            connection={latest ? view.connection : 'idle'}
            streamError={view.streamError}
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
