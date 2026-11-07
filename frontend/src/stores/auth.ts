import { computed, ref } from 'vue'

import { defineStore } from 'pinia'

import { getCurrentUser, login as loginRequest, logout as logoutRequest } from '@/api/auth'
import type { User } from '@/api/types'
import { clearToken, getToken, setToken } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const user = ref<User | null>(null)
  const isLoggingIn = ref(false)

  const isAuthenticated = computed(() => Boolean(token.value))

  function persistToken(value: string | null): void {
    token.value = value
    if (value) {
      setToken(value)
    } else {
      clearToken()
    }
  }

  function reset(): void {
    persistToken(null)
    user.value = null
  }

  async function login(payload: { username: string; password: string }): Promise<void> {
    isLoggingIn.value = true
    try {
      const session = await loginRequest(payload)
      persistToken(session.access_token)
      user.value = session.user
    } finally {
      isLoggingIn.value = false
    }
  }

  async function fetchCurrentUser(): Promise<User | null> {
    if (!token.value) {
      return null
    }
    const current = await getCurrentUser()
    user.value = current
    return current
  }

  async function logout(): Promise<void> {
    try {
      if (token.value) {
        await logoutRequest()
      }
    } catch {
      // 后端不可用时也要让本地会话立即失效
    } finally {
      reset()
    }
  }

  return {
    token,
    user,
    isLoggingIn,
    isAuthenticated,
    login,
    fetchCurrentUser,
    logout,
    reset,
  }
})
