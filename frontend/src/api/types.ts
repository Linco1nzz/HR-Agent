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

/** JD 状态（app/schemas/jd.py）。 */
export type JdStatus = 'draft' | 'generated' | 'published' | 'archived'

export interface JobDescriptionListItem {
  id: string
  title: string
  department: string | null
  location: string | null
  salary_range: string | null
  experience_level: string | null
  education: string | null
  job_type: string | null
  skills: string[] | null
  status: JdStatus
  content_preview: string
  created_at: string
  updated_at: string
}

export interface JobDescription {
  id: string
  title: string
  department: string | null
  location: string | null
  salary_range: string | null
  experience_level: string | null
  education: string | null
  job_type: string | null
  skills: string[] | null
  content: string
  requirements: string | null
  status: JdStatus
  meta_data: Record<string, unknown> | null
  conversation_id: string | null
  workflow_type: string
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface JobDescriptionListResponse {
  items: JobDescriptionListItem[]
  total: number
  page: number
  page_size: number
}

export interface JobDescriptionPayload {
  title: string
  department?: string | null
  location?: string | null
  salary_range?: string | null
  experience_level?: string | null
  education?: string | null
  job_type?: string | null
  skills?: string[] | null
  content: string
  requirements?: string | null
  status?: JdStatus
  meta_data?: Record<string, unknown> | null
  conversation_id?: string | null
  workflow_type?: string
}

export interface GenerateJdPayload {
  title: string
  department?: string | null
  location?: string | null
  salary_range?: string | null
  experience_level?: string | null
  education?: string | null
  job_type?: string | null
  skills?: string[] | null
  requirements?: string | null
}

export interface GenerateJdResponse {
  content: string
  conversation_id: string
  workflow_type: string
  task_id: string
  usage: Record<string, unknown> | null
}
