import axios, { AxiosError } from 'axios'

import type { ApiErrorBody } from '@/api/types'
import { getToken } from '@/utils/storage'

/** 前端统一业务异常：保留后端的 code / request_id，便于提示与排查。 */
export class ApiError extends Error {
  readonly status?: number
  readonly code?: string
  readonly requestId?: string

  constructor(
    message: string,
    options: { status?: number; code?: string; requestId?: string } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.requestId = options.requestId
  }
}

let unauthorizedHandler: (() => void) | null = null

/** 由 router 注册：令牌失效时清理会话并跳转登录页。 */
export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    const { response, config } = error
    const body = response?.data
    const url = config?.url ?? ''

    // 登录失败本身就是 401，不能触发全局登出跳转
    if (response?.status === 401 && !url.endsWith('/auth/login')) {
      unauthorizedHandler?.()
    }

    const message =
      body?.message ||
      (response ? `请求失败（HTTP ${response.status}）` : '网络异常，请检查后端服务是否已启动')

    return Promise.reject(
      new ApiError(message, {
        status: response?.status,
        code: body?.code,
        requestId: body?.request_id ?? undefined,
      }),
    )
  },
)
