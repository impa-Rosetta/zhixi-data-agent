import { tokenStorage } from './tokenStorage'
import type { TokenResponse } from './types'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: string | null = null,
  ) {
    super(message)
  }
}

function errorMessage(status: number, detail?: string): string {
  if (detail) return detail
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '你没有执行此操作的权限。'
  if (status === 409) return '当前状态存在冲突，请刷新后重试。'
  if (status === 429) return '请求过于频繁，请稍后再试。'
  return '服务暂时不可用，请稍后重试。'
}

export class ApiClient {
  private accessToken: string | null = null
  private refreshPromise: Promise<void> | null = null
  private authLostListener: (() => void) | null = null

  onAuthLost(listener: () => void): () => void {
    this.authLostListener = listener
    return () => {
      if (this.authLostListener === listener) this.authLostListener = null
    }
  }

  setTokens(tokens: TokenResponse): void {
    this.accessToken = tokens.access_token
    tokenStorage.set(tokens.refresh_token)
  }

  clearTokens(): void {
    this.accessToken = null
    tokenStorage.clear()
  }

  hasRefreshToken(): boolean {
    return tokenStorage.get() !== null
  }

  async logout(): Promise<void> {
    const refreshToken = tokenStorage.get()
    if (!refreshToken) return
    await this.raw('/api/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  }

  async refresh(): Promise<void> {
    if (this.refreshPromise) return this.refreshPromise
    const refreshToken = tokenStorage.get()
    if (!refreshToken) throw new ApiError(401, '没有可恢复的会话。')
    this.refreshPromise = this.raw<TokenResponse>('/api/v1/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then((tokens) => this.setTokens(tokens))
      .catch((reason: unknown) => {
        this.clearTokens()
        this.authLostListener?.()
        throw reason
      })
      .finally(() => {
        this.refreshPromise = null
      })
    return this.refreshPromise
  }

  async request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
    const headers = new Headers(init.headers)
    if (this.accessToken) headers.set('Authorization', `Bearer ${this.accessToken}`)
    try {
      return await this.raw<T>(path, { ...init, headers })
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401 && retry && this.hasRefreshToken()) {
        await this.refresh()
        return this.request<T>(path, init, false)
      }
      throw reason
    }
  }

  async requestStream(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'text/event-stream')
    if (this.accessToken) headers.set('Authorization', `Bearer ${this.accessToken}`)
    const response = await this.fetchResponse(path, { ...init, headers })
    if (response.status === 401 && retry && this.hasRefreshToken()) {
      await this.refresh()
      return this.requestStream(path, init, false)
    }
    if (!response.ok) throw await this.responseError(response)
    return response
  }

  async requestBlob(path: string, retry = true): Promise<Blob> {
    const headers = new Headers()
    if (this.accessToken) headers.set('Authorization', `Bearer ${this.accessToken}`)
    const response = await this.fetchResponse(path, { headers })
    if (response.status === 401 && retry && this.hasRefreshToken()) {
      await this.refresh()
      return this.requestBlob(path, false)
    }
    if (!response.ok) throw await this.responseError(response)
    return response.blob()
  }

  private async fetchResponse(path: string, init: RequestInit): Promise<Response> {
    try {
      return await fetch(`${apiBaseUrl}${path}`, init)
    } catch {
      throw new ApiError(0, '无法连接服务，请检查网络或稍后重试。')
    }
  }

  private async responseError(response: Response): Promise<ApiError> {
    let detail: string | undefined
    let code: string | null = null
    try {
      const body = (await response.json()) as {
        detail?: string | { code?: string; message?: string }
      }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) {
        detail = body.detail.message
        code = body.detail.code ?? null
      }
    } catch {
      detail = undefined
    }
    return new ApiError(response.status, errorMessage(response.status, detail), code)
  }

  private async raw<T>(path: string, init: RequestInit): Promise<T> {
    const headers = new Headers(init.headers)
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    const response = await this.fetchResponse(path, { ...init, headers })
    if (!response.ok) throw await this.responseError(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }
}

export const apiClient = new ApiClient()
