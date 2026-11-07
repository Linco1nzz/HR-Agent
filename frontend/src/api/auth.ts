import { http } from '@/api/http'

import type { LoginPayload, LogoutResponse, TokenResponse, User } from '@/api/types'

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await http.post<TokenResponse>('/auth/login', payload)
  return data
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await http.get<User>('/auth/me')
  return data
}

export async function logout(): Promise<LogoutResponse> {
  const { data } = await http.post<LogoutResponse>('/auth/logout')
  return data
}
