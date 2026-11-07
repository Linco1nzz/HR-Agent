/** 本地会话存储键。只存 JWT，用户信息每次刷新后从后端拉取。 */
const TOKEN_KEY = 'hr-agent:access-token'

export function getToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY)
}
