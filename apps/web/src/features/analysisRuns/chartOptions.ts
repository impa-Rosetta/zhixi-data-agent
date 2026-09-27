import type { EChartsCoreOption } from 'echarts/core'

export type ChartType = 'line' | 'bar' | 'horizontal_bar' | 'scatter'

export type SafeChartSpec = {
  chartType: ChartType
  title: string
  categoryField: string
  series: Array<{ field: string; label: string }>
  rowLimit: number
  truncated: boolean
}

export type QueryData = {
  columns: string[]
  rows: unknown[][]
}

const FIELD_LABELS: Record<string, string> = {
  defect_rate: '不良率',
  defect_quantity: '不良数量',
  inspected_quantity: '检验数量',
  inspection_time: '检验时间',
}

export function createSafeOption(
  spec: SafeChartSpec,
  data: QueryData,
): EChartsCoreOption | null {
  const allowedFields = new Set(data.columns)
  if (!allowedFields.has(spec.categoryField)) return null
  const series = spec.series.filter((item) => allowedFields.has(item.field))
  if (series.length === 0) return null
  const records = data.rows.slice(0, spec.rowLimit).map((row) =>
    Object.fromEntries(data.columns.map((column, index) => [column, safeValue(row[index])])),
  )
  const horizontal = spec.chartType === 'horizontal_bar'
  const scatter = spec.chartType === 'scatter'
  return {
    animation: false,
    color: ['#3155d9', '#16a269', '#d98a31', '#8b5cf6', '#dc4c64'],
    tooltip: { trigger: scatter ? 'item' : 'axis' },
    legend: { top: 4, right: 8, textStyle: { color: '#52627a', fontSize: 11 } },
    grid: { top: 48, right: 24, bottom: records.length > 12 ? 58 : 34, left: 58, containLabel: true },
    dataset: { source: records },
    xAxis: horizontal
      ? { type: 'value', axisLabel: { color: '#667085' }, splitLine: { lineStyle: { color: '#edf0f5' } } }
      : {
          type: scatter ? 'value' : 'category',
          axisLabel: { color: '#667085', hideOverlap: true },
          axisLine: { lineStyle: { color: '#cfd7e3' } },
        },
    yAxis: horizontal
      ? { type: 'category', axisLabel: { color: '#667085' }, axisLine: { lineStyle: { color: '#cfd7e3' } } }
      : { type: 'value', axisLabel: { color: '#667085' }, splitLine: { lineStyle: { color: '#edf0f5' } } },
    dataZoom: records.length > 12
      ? [{ type: 'inside', start: 0, end: Math.max(20, Math.floor(1200 / records.length)) }, { type: 'slider', height: 16 }]
      : [],
    series: series.map((item) => ({
      name: displaySeriesLabel(item.label, item.field),
      type: spec.chartType === 'line' ? 'line' : spec.chartType === 'scatter' ? 'scatter' : 'bar',
      encode: horizontal
        ? { x: item.field, y: spec.categoryField }
        : { x: spec.categoryField, y: item.field },
      showSymbol: spec.chartType !== 'line' || records.length <= 30,
      smooth: false,
      connectNulls: false,
      emphasis: { focus: 'series' },
    })),
  }
}

function safeValue(value: unknown): string | number | null {
  if (typeof value === 'string') return value.slice(0, 500)
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'boolean') return value ? 1 : 0
  return null
}

function displaySeriesLabel(label: string, field: string): string {
  return label === field ? (FIELD_LABELS[field] ?? label) : label
}
