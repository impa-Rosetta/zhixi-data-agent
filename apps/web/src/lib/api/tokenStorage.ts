const refreshTokenKey = 'zhixi.refresh-token'

export const tokenStorage = {
  get(): string | null {
    return window.localStorage.getItem(refreshTokenKey)
  },
  set(token: string): void {
    window.localStorage.setItem(refreshTokenKey, token)
  },
  clear(): void {
    window.localStorage.removeItem(refreshTokenKey)
  },
}
