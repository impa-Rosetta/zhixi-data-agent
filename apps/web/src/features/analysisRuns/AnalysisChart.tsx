import { useEffect, useMemo, useRef } from 'react'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use as registerEChartsComponents, type EChartsCoreOption } from 'echarts/core'
import { LegacyGridContainLabel } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'

import type { AnalysisArtifact } from './types'

registerEChartsComponents([
  BarChart,
  LineChart,
  ScatterChart,
  DataZoomComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  LegacyGridContainLabel,
  SVGRenderer,
])

type ChartType = 'line' | 'bar' | 'horizontal_bar' | 'scatter'

type SafeChartSpec = {
  chartType: ChartType
  title: string
  categoryField: string
  series: Array<{ field: string; label: string }>
  rowLimit: number
  truncated: boolean
}

type QueryData = {
  columns: string[]
  rows: unknown[][]
}

const FIELD_LABELS: Record<string, string> = {
  defect_rate: '不良率',
  defect_quantity: '不良数量',
  inspected_quantity: '检验数量',
  inspection_time: '检验时间',
}

export function AnalysisChart({
  artifact,
  source,
}: {
  artifact: AnalysisArtifact
  source: AnalysisArtifact
}) {
  const container = useRef<HTMLDivElement>(null)
  const spec = useMemo(() => readChartSpec(artifact), [artifact])
  const data = useMemo(() => readQueryData(source), [source])
  const option = useMemo(
    () => spec && data ? createSafeOption(spec, data) : null,
    [data, spec],
  )

  useEffect(() => {
    const element = container.current
    if (!element || !option || element.clientWidth === 0) return
    const chart = init(element, undefined, { renderer: 'svg' })
    chart.setOption(option, { notMerge: true })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [option])

  if (!spec || !data || !option) return null
  return (
    <section className="analysis-chart-card" aria-label="分析图表">
      <header>
        <div>
          <p className="analysis-kicker">受限 ChartSpec</p>
          <h4>{spec.title}</h4>
        </div>
        <span>{chartTypeLabel(spec.chartType)}</span>
      </header>
      <div
        ref={container}
        className="analysis-chart-canvas"
        role="img"
        aria-label={spec.title + ' ' + chartTypeLabel(spec.chartType)}
      />
      {spec.truncated && <p className="analysis-chart-note">图表按安全行数上限展示，完整结果仍保留在表格中。</p>}
    </section>
  )
}

function readChartSpec(artifact: AnalysisArtifact): SafeChartSpec | null {
  const summary = artifact.summary
  const chartType = summary.chart_type
  const title = summary.title
  const categoryField = summary.category_field
  const rawSeries: unknown = summary.series
  if (
    summary.version !== 1
    || !isChartType(chartType)
    || typeof title !== 'string'
    || typeof categoryField !== 'string'
    || !Array.isArray(rawSeries)
  ) return null
  const series = rawSeries.flatMap((item: unknown) => {
    if (
      typeof item !== 'object'
      || item === null
      || Array.isArray(item)
      || !('field' in item)
      || !('label' in item)
      || typeof item.field !== 'string'
      || typeof item.label !== 'string'
    ) return []
    return [{ field: item.field, label: item.label }]
  }).slice(0, 10)
  if (series.length === 0) return null
  return {
    chartType,
    title: title.slice(0, 200),
    categoryField,
    series,
    rowLimit: typeof summary.row_limit === 'number'
      ? Math.max(1, Math.min(200, Math.floor(summary.row_limit)))
      : 200,
    truncated: summary.truncated === true,
  }
}

function readQueryData(artifact: AnalysisArtifact): QueryData | null {
  const columns = Array.isArray(artifact.summary.columns)
    ? artifact.summary.columns.filter((item): item is string => typeof item === 'string')
    : []
  const rows = Array.isArray(artifact.summary.rows)
    ? artifact.summary.rows.filter((item): item is unknown[] => Array.isArray(item))
    : []
  return columns.length > 1 && rows.length > 1 ? { columns, rows } : null
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

function isChartType(value: unknown): value is ChartType {
  return value === 'line' || value === 'bar' || value === 'horizontal_bar' || value === 'scatter'
}

function chartTypeLabel(value: ChartType): string {
  return {
    line: '折线图',
    bar: '柱状图',
    horizontal_bar: '横向柱状图',
    scatter: '散点图',
  }[value]
}
