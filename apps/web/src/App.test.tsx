import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { App } from './App'

afterEach(() => vi.restoreAllMocks())

test('shows the product identity and API health', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ status: 'ok', service: 'api', version: '0.1.0' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  render(<App />)

  expect(screen.getByRole('heading', { name: '智析 Data Agent' })).toBeInTheDocument()
  expect(await screen.findByText('API 0.1.0 已连接')).toBeInTheDocument()
})

