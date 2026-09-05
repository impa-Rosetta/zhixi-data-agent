import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { ApiClient, ApiError } from './client'

const refreshTokenKey = 'zhixi.refresh-token'

beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

afterEach(() => vi.restoreAllMocks())

test('refreshes once and retries a protected request after a 401', async () => {
  window.localStorage.setItem(refreshTokenKey, 'refresh-old')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      access_token: 'access-new',
      refresh_token: 'refresh-new',
      token_type: 'bearer',
      expires_in: 900,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'user-1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

  const client = new ApiClient()
  await expect(client.request<{ id: string }>('/api/v1/auth/me')).resolves.toEqual({ id: 'user-1' })

  expect(fetchMock).toHaveBeenCalledTimes(3)
  const retriedRequest = fetchMock.mock.calls[2]?.[1]
  expect(new Headers(retriedRequest?.headers).get('Authorization')).toBe('Bearer access-new')
  expect(window.localStorage.getItem(refreshTokenKey)).toBe('refresh-new')
})

test('clears the stored session and reports auth loss when refresh fails', async () => {
  window.localStorage.setItem(refreshTokenKey, 'invalid-refresh')
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ detail: 'invalid session' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  const onAuthLost = vi.fn()
  const client = new ApiClient()
  client.onAuthLost(onAuthLost)

  await expect(client.refresh()).rejects.toBeInstanceOf(ApiError)

  expect(window.localStorage.getItem(refreshTokenKey)).toBeNull()
  expect(onAuthLost).toHaveBeenCalledOnce()
})
