import { useState } from 'react'

import type { Catalog, SamplingPolicy, ScanSchedule } from '../../lib/api/types'
import { useCatalog, useSamplingPolicy, useScanSchedule, useUpdateSamplingPolicy, useUpdateScanSchedule } from '../dataSources/api'

type Props = { workspaceId: string; dataSourceId: string; snapshotId: string }
type TableOption = { schema_name: string; table_name: string }

function tablesFromCatalog(catalog: Catalog | undefined): TableOption[] {
  return (catalog?.schemas ?? []).flatMap((schema) => schema.relations
    .filter((relation) => relation.relation_type === 'table')
    .map((relation) => ({ schema_name: schema.name, table_name: relation.name })))
}

function SamplingEditor({ workspaceId, dataSourceId, policy, tables }: { workspaceId: string; dataSourceId: string; policy: SamplingPolicy; tables: TableOption[] }) {
  const update = useUpdateSamplingPolicy(workspaceId, dataSourceId)
  const [enabled, setEnabled] = useState(policy.enabled)
  const [selected, setSelected] = useState(() => new Set(policy.table_allowlist.map((item) => item.schema_name + '.' + item.table_name)))
  const [rows, setRows] = useState(policy.max_rows_per_table)
  const [values, setValues] = useState(policy.max_values_per_column)
  const [chars, setChars] = useState(policy.max_value_chars)
  const [tableBytes, setTableBytes] = useState(policy.max_bytes_per_table)
  const [jobBytes, setJobBytes] = useState(policy.max_bytes_per_job)
  const [timeout, setTimeoutSeconds] = useState(policy.statement_timeout_seconds)
  const [message, setMessage] = useState<string | null>(null)

  function toggleTable(table: TableOption) {
    const key = table.schema_name + '.' + table.table_name
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  async function save() {
    const scopes = tables.filter((table) => selected.has(table.schema_name + '.' + table.table_name))
    if (enabled && scopes.length === 0) { setMessage('启用采样前至少选择一个普通表。'); return }
    setMessage(null)
    try {
      await update.mutateAsync({
        version: policy.version, enabled,
        schema_allowlist: [...new Set(scopes.map((item) => item.schema_name))],
        table_allowlist: scopes, max_rows_per_table: rows, max_values_per_column: values,
        max_value_chars: chars, max_bytes_per_table: tableBytes, max_bytes_per_job: jobBytes,
        statement_timeout_seconds: timeout,
      })
      setMessage('采样策略已保存，下一次元数据扫描将冻结该版本。')
    } catch { setMessage('采样策略保存失败，请刷新后重试。') }
  }

  return <section className="policy-box"><header><div><h3>安全采样策略</h3><p>默认关闭，只对明确授权的普通表执行有界读取。</p></div><label className="switch-label"><input type="checkbox" aria-label="启用安全采样" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>{enabled ? '已启用' : '已关闭'}</span></label></header>
    <div className="table-scope"><strong>允许采样的表</strong>{tables.map((table) => <label key={table.schema_name + '.' + table.table_name}><input type="checkbox" aria-label={'允许采样 ' + table.schema_name + '.' + table.table_name} checked={selected.has(table.schema_name + '.' + table.table_name)} onChange={() => toggleTable(table)} /><code>{table.schema_name}.{table.table_name}</code></label>)}</div>
    <div className="budget-grid">
      <label><span>每表最大行数</span><input aria-label="每表最大行数" type="number" min="1" max="20" value={rows} onChange={(e) => setRows(Number(e.target.value))} /></label>
      <label><span>每字段最大样例</span><input type="number" min="1" max="20" value={values} onChange={(e) => setValues(Number(e.target.value))} /></label>
      <label><span>单值最大字符</span><input type="number" min="16" max="256" value={chars} onChange={(e) => setChars(Number(e.target.value))} /></label>
      <label><span>单表字节</span><input type="number" min="1024" max="1048576" value={tableBytes} onChange={(e) => setTableBytes(Number(e.target.value))} /></label>
      <label><span>单任务字节</span><input type="number" min="1024" max="10485760" value={jobBytes} onChange={(e) => setJobBytes(Number(e.target.value))} /></label>
      <label><span>语句超时（秒）</span><input type="number" min="1" max="10" value={timeout} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} /></label>
    </div>
    {message && <p className="policy-message">{message}</p>}<footer><span>策略版本 v{policy.version}</span><button className="primary-button" disabled={update.isPending} onClick={() => void save()}>保存采样策略</button></footer>
  </section>
}

function ScheduleEditor({ workspaceId, dataSourceId, schedule }: { workspaceId: string; dataSourceId: string; schedule: ScanSchedule | null }) {
  const update = useUpdateScanSchedule(workspaceId, dataSourceId)
  const [enabled, setEnabled] = useState(schedule?.enabled ?? false)
  const [frequency, setFrequency] = useState<'daily' | 'weekly'>(schedule?.frequency ?? 'daily')
  const [timezone, setTimezone] = useState(schedule?.timezone ?? 'Asia/Shanghai')
  const [localTime, setLocalTime] = useState((schedule?.local_time ?? '03:30:00').slice(0, 5))
  const [day, setDay] = useState(schedule?.day_of_week ?? 1)
  const [message, setMessage] = useState<string | null>(null)
  async function save() {
    setMessage(null)
    try {
      await update.mutateAsync({ version: schedule?.version ?? 0, enabled, frequency, timezone, local_time: localTime + ':00', day_of_week: frequency === 'weekly' ? day : null })
      setMessage('刷新计划已保存。')
    } catch { setMessage('刷新计划保存失败，请检查时区或刷新版本。') }
  }
  return <section className="policy-box"><header><div><h3>定时刷新</h3><p>按业务时区触发元数据扫描，计划状态由数据库持久化。</p></div><label className="switch-label"><input type="checkbox" aria-label="启用定时刷新" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>{enabled ? '已启用' : '已关闭'}</span></label></header>
    <div className="schedule-grid"><label><span>频率</span><select value={frequency} onChange={(e) => setFrequency(e.target.value as 'daily' | 'weekly')}><option value="daily">每天</option><option value="weekly">每周</option></select></label>{frequency === 'weekly' && <label><span>星期</span><select value={day} onChange={(e) => setDay(Number(e.target.value))}>{['周一','周二','周三','周四','周五','周六','周日'].map((label, index) => <option key={label} value={index}>{label}</option>)}</select></label>}<label><span>IANA时区</span><input value={timezone} onChange={(e) => setTimezone(e.target.value)} /></label><label><span>执行时间</span><input type="time" value={localTime} onChange={(e) => setLocalTime(e.target.value)} /></label></div>
    {schedule?.next_run_at && <p className="next-run">下次执行：{new Date(schedule.next_run_at).toLocaleString('zh-CN')}</p>}{message && <p className="policy-message">{message}</p>}<footer><span>计划版本 v{schedule?.version ?? 0}</span><button className="primary-button" disabled={update.isPending} onClick={() => void save()}>保存刷新计划</button></footer>
  </section>
}

export function DataSourcePoliciesPanel({ workspaceId, dataSourceId, snapshotId }: Props) {
  const catalog = useCatalog(workspaceId, dataSourceId, snapshotId)
  const policy = useSamplingPolicy(workspaceId, dataSourceId)
  const schedule = useScanSchedule(workspaceId, dataSourceId)
  return <section className="detail-section policies-section"><div className="section-heading"><div><p className="eyebrow">数据治理控制</p><h2>采样与刷新</h2></div><span>最小授权 · 硬预算</span></div>
    {(catalog.isPending || policy.isPending || schedule.isPending) && <div className="policy-loading"><span className="spinner" />正在读取治理策略…</div>}
    {(catalog.isError || policy.isError || schedule.isError) && <div className="alert error">治理策略读取失败，请稍后重试。</div>}
    {catalog.data && policy.data && schedule.data !== undefined && <div className="policies-grid"><SamplingEditor key={policy.data.version} workspaceId={workspaceId} dataSourceId={dataSourceId} policy={policy.data} tables={tablesFromCatalog(catalog.data)} /><ScheduleEditor key={schedule.data?.version ?? 0} workspaceId={workspaceId} dataSourceId={dataSourceId} schedule={schedule.data} /></div>}
  </section>
}
