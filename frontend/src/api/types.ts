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
  criteria_count: number
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

/** 评分标准状态（app/schemas/scoring_criteria.py）。 */
export type ScoringCriteriaStatus = 'draft' | 'generated' | 'published' | 'archived'

export interface ScoringDimension {
  name?: string
  score?: number | string
  weight?: number | string
  description?: string
  [key: string]: unknown
}

export interface ScoringCriteriaListItem {
  id: string
  title: string
  job_title: string | null
  total_score: string
  status: ScoringCriteriaStatus
  job_description_id: string | null
  dimension_count: number
  content_preview: string
  created_at: string
  updated_at: string
}

export interface ScoringCriteria {
  id: string
  title: string
  job_title: string | null
  content: string
  criteria_data: Record<string, unknown> | null
  total_score: string
  scoring_dimensions: ScoringDimension[] | null
  status: ScoringCriteriaStatus
  meta_data: Record<string, unknown> | null
  conversation_id: string | null
  workflow_type: string
  job_description_id: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface ScoringCriteriaListResponse {
  items: ScoringCriteriaListItem[]
  total: number
  page: number
  page_size: number
}

export interface ScoringCriteriaPayload {
  title: string
  job_title?: string | null
  content: string
  criteria_data?: Record<string, unknown> | null
  total_score?: string
  scoring_dimensions?: ScoringDimension[] | null
  status?: ScoringCriteriaStatus
  meta_data?: Record<string, unknown> | null
  conversation_id?: string | null
  workflow_type?: string
  job_description_id?: string | null
}

export interface GenerateScoringCriteriaPayload {
  job_description_id: string
  title?: string | null
  total_score?: string
  instructions?: string | null
}

export interface GenerateScoringCriteriaResponse {
  title: string
  job_title: string | null
  content: string
  total_score: string
  scoring_dimensions: ScoringDimension[] | null
  criteria_data: Record<string, unknown> | null
  job_description_id: string | null
  conversation_id: string
  workflow_type: string
  task_id: string
  usage: Record<string, unknown> | null
}

/** 简历复核状态（app/schemas/resume_evaluation.py）。 */
export type ResumeStatus = 'pending' | 'interview' | 'rejected'

export interface EvaluationMetric {
  name: string
  score: number
  max: number
  reason: string
}

export interface ResumeEvaluationListItem {
  id: string
  original_filename: string
  file_type: string
  file_size: number
  candidate_name: string | null
  candidate_position: string | null
  work_years: number | null
  education_level: string | null
  total_score: number | null
  max_score: number | null
  metric_count: number
  status: ResumeStatus
  job_title: string | null
  job_description_id: string
  scoring_criteria_id: string
  scoring_criteria_title: string | null
  created_at: string
  updated_at: string
}

export interface ResumeEvaluation extends ResumeEvaluationListItem {
  candidate_age: number | null
  candidate_gender: string | null
  school: string | null
  resume_content: string
  evaluation_metrics: EvaluationMetric[]
  ai_answer: string | null
  conversation_id: string | null
  created_by: string | null
}

export interface ResumeEvaluationListResponse {
  items: ResumeEvaluationListItem[]
  total: number
  page: number
  page_size: number
}

export interface ResumeEvaluationStatusPayload {
  status: ResumeStatus
}
