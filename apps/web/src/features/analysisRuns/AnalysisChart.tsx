import { useEffect, useMemo, useRef } from 'react'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use as registerEChartsComponents } from 'echarts/core'
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

import { createSafeOption, type ChartType, type SafeChartSpec, type QueryData } from './chartOptions'

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
