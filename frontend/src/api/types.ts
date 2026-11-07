/** 与后端 Pydantic Schema 对应的类型定义。 */

export interface User {
  id: string
  username: string
  email: string
  full_name: string | null
  phone: string | null
  department: string | null
  position: string | null
  employee_id: string | null
  is_superuser: boolean
  is_verified: boolean
  is_active: boolean
  bio: string | null
  avatar_url: string | null
  last_login: string | null
  roles: string[]
}

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface LogoutResponse {
  message: string
}

/** 后端统一错误响应（app/schemas/error.py）。 */
export interface ApiErrorBody {
  code: string
  message: string
  details?: Record<string, unknown> | null
  request_id?: string | null
  timestamp: string
}
