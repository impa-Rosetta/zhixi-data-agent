import { init } from 'echarts/core'
import { expect, test } from 'vitest'

import { createSafeOption } from './chartOptions'
import './AnalysisChart'

test('renders trusted dataset rows into the SVG chart', () => {
  const option = createSafeOption(
    {
      chartType: 'line',
      title: '最近三个月的不良率趋势',
      categoryField: 'inspection_time',
      series: [{ field: 'defect_rate', label: 'defect_rate' }],
      rowLimit: 3,
      truncated: false,
    },
    {
      columns: ['inspection_time', 'defect_rate'],
      rows: [
        ['2026-07', 1.75],
        ['2026-08', 2.75],
        ['2026-09', 3],
      ],
    },
  )
  expect(option).not.toBeNull()

  const chart = init(null, undefined, {
    renderer: 'svg',
    ssr: true,
    width: 800,
    height: 340,
  })
  chart.setOption(option!)
  const svg = chart.renderToSVGString()
  chart.dispose()

  expect(svg).toContain('2026-07')
  expect(svg).toContain('2026-08')
  expect(svg).toContain('2026-09')
  expect(svg).toContain('不良率')
})

test('orders a monthly inspection trend chronologically without changing source rows', () => {
  const rows: unknown[][] = [
    ['2026-09-01T00:00:00+00:00', 3],
    ['2026-08-01T00:00:00+00:00', 2.75],
    ['2026-07-01T00:00:00+00:00', 1.75],
  ]
  const option = createSafeOption(
    {
      chartType: 'line', title: '最近三个月的不良率趋势',
      categoryField: 'inspection_time', series: [{ field: 'defect_rate', label: 'defect_rate' }],
      rowLimit: 3, truncated: false,
    },
    { columns: ['inspection_time', 'defect_rate'], rows },
  ) as unknown as {
    dataset: { source: Array<{ inspection_time: string; defect_rate: number }> }
    xAxis: { axisLabel: { formatter: (value: string) => string } }
  }

  expect(option.dataset.source.map((row) => [row.inspection_time, row.defect_rate])).toEqual([
    ['2026-07-01T00:00:00+00:00', 1.75],
    ['2026-08-01T00:00:00+00:00', 2.75],
    ['2026-09-01T00:00:00+00:00', 3],
  ])
  expect(option.xAxis.axisLabel.formatter('2026-09-01T00:00:00+00:00')).toBe('2026-09-01')
  expect(rows[0]).toEqual(['2026-09-01T00:00:00+00:00', 3])
})

test('renders a real scatter dataset as visible SVG points', () => {
  const option = createSafeOption({ chartType: 'scatter', title: '相关性散点图', categoryField: 'x',
    series: [{ field: 'y', label: '指标Y' }], rowLimit: 10, truncated: false },
  { columns: ['x', 'y'], rows: [[1, 3], [2, 5], [3, 8]] })
  const chart = init(null, undefined, { renderer: 'svg', ssr: true, width: 800, height: 340 })
  try {
    chart.setOption(option!)
    const svg = chart.renderToSVGString()
    expect(svg).toContain('指标Y')
    expect(svg).toContain('<path')
    expect(svg).not.toContain('NaN')
  } finally { chart.dispose() }
})

test('renders IQR candidate markers in red rather than a blank chart', () => {
  const option = createSafeOption({ chartType: 'line', title: '异常检测', categoryField: 'row_index',
    series: [{ field: 'value', label: '指标' }, { field: 'anomaly_value', label: '异常点' }],
    rowLimit: 10, truncated: false }, { columns: ['row_index', 'value', 'anomaly_value'],
    rows: [[1, 1, null], [2, 2, null], [3, 100, 100]] })
  const chart = init(null, undefined, { renderer: 'svg', ssr: true, width: 800, height: 340 })
  try {
    chart.setOption(option!)
    const svg = chart.renderToSVGString()
    expect(svg).toContain('异常点')
    expect(svg).toContain('#dc4c64')
    expect(svg).not.toContain('NaN')
  } finally { chart.dispose() }
})
