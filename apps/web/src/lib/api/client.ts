import { tokenStorage } from './tokenStorage'
import type { TokenResponse } from './types'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
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

  private async raw<T>(path: string, init: RequestInit): Promise<T> {
    const headers = new Headers(init.headers)
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    let response: Response
    try {
      response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers })
    } catch {
      throw new ApiError(0, '无法连接服务，请检查网络或稍后重试。')
    }
    if (!response.ok) {
      let detail: string | undefined
      try {
        const body = (await response.json()) as { detail?: string }
        detail = body.detail
      } catch {
        detail = undefined
      }
      throw new ApiError(response.status, errorMessage(response.status, detail))
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }
}

export const apiClient = new ApiClient()
