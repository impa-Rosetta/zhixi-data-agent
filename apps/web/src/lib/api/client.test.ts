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

test('parses structured API errors without losing the stable error code', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    detail: { code: 'data_source.conflict', message: '数据源名称已存在' },
  }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
  const client = new ApiClient()

  try {
    await client.request('/api/v1/example')
    throw new Error('request should fail')
  } catch (reason) {
    expect(reason).toBeInstanceOf(ApiError)
    expect(reason).toMatchObject({ status: 409, code: 'data_source.conflict', message: '数据源名称已存在' })
  }
})

test('opens an authenticated event stream without consuming the response body', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response('id: 1\ndata: {}\n\n', {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
  )
  const client = new ApiClient()
  client.setTokens({
    access_token: 'stream-access',
    refresh_token: 'stream-refresh',
    token_type: 'bearer',
    expires_in: 900,
  })

  const response = await client.requestStream('/api/v1/example/events')

  expect(response.headers.get('Content-Type')).toBe('text/event-stream')
  const request = fetchMock.mock.calls[0]?.[1]
  expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer stream-access')
  expect(new Headers(request?.headers).get('Accept')).toBe('text/event-stream')
  await expect(response.text()).resolves.toContain('id: 1')
})
