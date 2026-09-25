import { useState, type FormEvent } from 'react'

import type { AnalysisConversationView } from '../analysisRuns/types'
import { downloadReportFile, useConversationReports, useCreateConversationReport, type ReportFormat } from './api'
import { ApiError } from '../../lib/api/client'

type Props = {
  view: AnalysisConversationView
}

const formatNames: Record<ReportFormat, string> = {
  markdown: 'Markdown',
  html: 'HTML',
  pdf: 'PDF',
}

const extensions: Record<ReportFormat, string> = {
  markdown: 'md',
  html: 'html',
  pdf: 'pdf',
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'report.validation_required') return '所选轮次缺少可信验证结果，请选择有数据和证据的分析。'
    if (error.code === 'analysis_report.turn_not_completed') return '所选分析尚未完成，请完成后再生成报告。'
    if (error.code === 'analysis_report.not_ready') return '报告仍在生成，请稍后再试。'
    if (error.code === 'analysis_report.integrity_failed') return '报告文件校验失败，已阻止下载。'
  }
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

function newIdempotencyKey(): string {
  return typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function ConversationReports({ view }: Props) {
  const workspaceId = view.conversation.workspace_id
  const conversationId = view.conversation.id
  const reports = useConversationReports(workspaceId, conversationId)
  const create = useCreateConversationReport(workspaceId, conversationId)
  const [title, setTitle] = useState(`${view.conversation.title}报告`)
  const [excluded, setExcluded] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<string | null>(null)

  const eligible = view.turns.filter(({ turn, analysis }) => {
    if (turn.status !== 'completed' || analysis.run.status !== 'completed') return false
    const trusted = analysis.artifacts.filter((artifact) =>
      ['query_result', 'analysis_summary', 'chart_spec'].includes(artifact.artifact_type),
    )
    return trusted.some((artifact) =>
      analysis.evidence.some((evidence) => evidence.artifact_id === artifact.id),
    ) && analysis.validations.some((validation) => validation.outcome === 'passed')
  })
  const selected = eligible.filter(({ turn }) => !excluded.includes(turn.id)).map(({ turn }) => turn.id)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (selected.length === 0 || !title.trim()) return
    setError(null)
    try {
      await create.mutateAsync({
        title: title.trim(),
        turnIds: selected,
        idempotencyKey: newIdempotencyKey(),
      })
    } catch (reason) {
      setError(errorText(reason))
    }
  }

  const download = async (reportId: string, reportTitle: string, format: ReportFormat) => {
    setError(null)
    setDownloading(`${reportId}:${format}`)
    try {
      const blob = await downloadReportFile(workspaceId, reportId, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${reportTitle.replace(/[\\/:*?"<>|]/g, '_')}.${extensions[format]}`
      document.body.append(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setDownloading(null)
    }
  }

  return (
    <section className="conversation-reports" aria-label="可信分析报告">
      <header>
        <div>
          <p className="analysis-kicker">可信报告</p>
          <h3>从已验证的分析生成报告</h3>
        </div>
        <span>{eligible.length} 轮可选</span>
      </header>
      {eligible.length === 0 ? (
        <p className="conversation-reports-note">
          当前会话还没有同时具备数据结果、验证和证据的已完成轮次。完成一次可信分析后即可生成报告。
        </p>
      ) : (
        <form onSubmit={(event) => void submit(event)}>
          <fieldset>
            <legend>选择报告内容</legend>
            {eligible.map(({ turn, analysis }) => (
              <label key={turn.id}>
                <input
                  type="checkbox"
                  checked={!excluded.includes(turn.id)}
                  onChange={(event) => setExcluded((current) => event.target.checked
                    ? current.filter((id) => id !== turn.id)
                    : [...current, turn.id])}
                />
                第 {turn.sequence} 轮 · {analysis.messages.find((item) => item.role === 'user')?.content ?? '分析结果'}
              </label>
            ))}
          </fieldset>
          <div className="conversation-reports-create">
            <label htmlFor="report-title">报告标题</label>
            <input
              id="report-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={300}
            />
            <button type="submit" className="secondary-button" disabled={create.isPending || selected.length === 0 || !title.trim()}>
              {create.isPending ? '正在提交…' : '生成报告'}
            </button>
          </div>
        </form>
      )}
      {reports.isLoading && <p className="conversation-reports-note">正在读取报告…</p>}
      {reports.isError && <p className="analysis-inline-error" role="alert">报告列表暂时无法加载，请稍后重试。</p>}
      {reports.data?.items.map((report) => (
        <article className="conversation-report-item" key={report.id}>
          <div>
            <strong>{report.title}</strong>
            <span aria-live="polite">{{
              queued: '等待生成',
              generating: '正在生成',
              succeeded: '已生成',
              failed: '生成失败',
              expired: '已过期',
            }[report.status]}</span>
          </div>
          {report.status === 'succeeded' ? (
            <nav aria-label={`下载${report.title}`}>
              {(['markdown', 'html', 'pdf'] as const).map((format) => (
                <button
                  type="button"
                  key={format}
                  disabled={downloading !== null}
                  onClick={() => void download(report.id, report.title, format)}
                >
                  {downloading === `${report.id}:${format}` ? '下载中…' : formatNames[format]}
                </button>
              ))}
            </nav>
          ) : report.status === 'failed' && (
            <p>本次生成未完成。请重新选择可信轮次创建报告；自动恢复功能仍在完善。</p>
          )}
        </article>
      ))}
      {error && <p className="analysis-inline-error" role="alert">{error}</p>}
    </section>
  )
}
