import { init } from 'echarts/core'
import { expect, test } from 'vitest'

import { createSafeOption } from './AnalysisChart'

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
