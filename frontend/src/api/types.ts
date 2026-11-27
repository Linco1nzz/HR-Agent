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

/** 面试方案（app/schemas/interview_plan.py）。 */
export interface InterviewPlanListItem {
  id: string
  candidate_name: string
  candidate_position: string
  resume_evaluation_id: string
  job_title: string | null
  content_preview: string
  created_at: string
  updated_at: string
}

export interface InterviewPlan {
  id: string
  candidate_name: string
  candidate_position: string
  content: string
  resume_evaluation_id: string
  job_title: string | null
  job_description_id: string | null
  conversation_id: string | null
  workflow_type: string
  meta_data: Record<string, unknown> | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface InterviewPlanListResponse {
  items: InterviewPlanListItem[]
  total: number
  page: number
  page_size: number
}

export interface InterviewPlanPayload {
  candidate_name: string
  candidate_position: string
  content: string
  resume_evaluation_id: string
  conversation_id?: string | null
  meta_data?: Record<string, unknown> | null
}

export interface InterviewPlanUpdatePayload {
  candidate_name?: string
  candidate_position?: string
  content?: string
}

export interface GenerateInterviewPlanPayload {
  resume_evaluation_id: string
  instructions?: string | null
}

export interface GenerateInterviewPlanResponse {
  content: string
  candidate_name: string
  candidate_position: string
  resume_evaluation_id: string
  job_title: string | null
  job_description_id: string | null
  conversation_id: string
  workflow_type: string
  task_id: string
  usage: Record<string, unknown> | null
}

export type InterviewPlanExportFormat = 'docx' | 'markdown'

/** 知识库（app/schemas/knowledge_base.py）。 */
export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  is_public: boolean
  is_searchable: boolean
  meta_data: Record<string, unknown> | null
  document_count: number
  category: string | null
  tags: string[] | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseListResponse {
  items: KnowledgeBase[]
  total: number
  page: number
  page_size: number
}

export interface KnowledgeBasePayload {
  name: string
  description?: string | null
  is_public?: boolean
  is_searchable?: boolean
  meta_data?: Record<string, unknown> | null
  category?: string | null
  tags?: string[] | null
}

export type KnowledgeBaseUpdatePayload = Partial<KnowledgeBasePayload>

/** 文档处理状态（app/schemas/document.py）。 */
export type DocumentProcessingStatus = 'uploaded' | 'processing' | 'processed' | 'failed'

export interface KnowledgeDocumentListItem {
  id: string
  knowledge_base_id: string | null
  knowledge_base_name: string | null
  original_filename: string
  mime_type: string
  file_size: number
  processing_status: DocumentProcessingStatus
  processing_error: string | null
  chunk_count: number
  category: string | null
  tags: string[] | null
  processed_at: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeDocument extends KnowledgeDocumentListItem {
  filename: string
  file_hash: string
  meta_data: Record<string, unknown> | null
  user_id: string
  created_by: string | null
}

export interface KnowledgeDocumentListResponse {
  items: KnowledgeDocumentListItem[]
  total: number
  page: number
  page_size: number
}

export interface DocumentContentResponse {
  document_id: string
  original_filename: string
  mime_type: string
  content: string
  char_count: number
  chunk_count: number
  processing_status: DocumentProcessingStatus
}

export interface DocumentChunkItem {
  id: string
  chunk_index: number
  content: string
  char_count: number
  has_embedding: boolean
  meta_data: Record<string, unknown> | null
}

export interface DocumentChunkListResponse {
  document_id: string
  items: DocumentChunkItem[]
  total: number
}

/** 会话（app/schemas/conversation.py）。 */
export type ConversationStatus = 'active' | 'archived'

/** 会话类型：知识问答 / HR Agent。 */
export type ConversationKind = 'knowledge' | 'agent'

export interface Conversation {
  id: string
  title: string
  kind: ConversationKind
  description: string | null
  status: ConversationStatus
  knowledge_base_ids: string[]
  total_messages: number
  meta_data: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ConversationListResponse {
  items: Conversation[]
  total: number
  page: number
  page_size: number
}

export interface ConversationPayload {
  title?: string
  description?: string | null
  kind?: ConversationKind
  knowledge_base_ids?: string[]
}

export interface ConversationUpdatePayload {
  title?: string
  description?: string | null
  status?: ConversationStatus
  knowledge_base_ids?: string[]
}

/** 会话消息（app/schemas/conversation.py）。 */
export type ChatRole = 'user' | 'assistant'

/** 回答路由：kb 走知识库检索，direct 由模型直接回答。 */
export type ChatRoute = 'kb' | 'direct'

export interface ChatSource {
  chunk_id: string
  document_id: string
  document_name: string
  knowledge_base_id: string
  chunk_index: number
  score: number
  content: string
}

export interface ChatContext {
  route: ChatRoute
  reason?: string | null
  rewritten_query?: string | null
  keywords?: string[] | null
  sources?: ChatSource[] | null
}

export interface ChatMessage {
  id: string
  conversation_id: string
  role: ChatRole
  content: string
  model_name: string | null
  tokens_used: number | null
  response_time: number | null
  context: ChatContext | null
  meta_data: Record<string, unknown> | null
  rating: number | null
  feedback: string | null
  parent_message_id: string | null
  created_at: string
}

export interface ChatMessageListResponse {
  items: ChatMessage[]
  total: number
  page: number
  page_size: number
}

export interface MessageFeedbackPayload {
  rating: number
  feedback?: string | null
}

/** POST /conversations/{id}/chat 的 SSE 事件载荷。 */
export interface ChatMetaEvent {
  user_message_id: string
  assistant_message_id: string
  route: ChatRoute
  reason?: string | null
  rewritten_query?: string | null
  keywords?: string[] | null
}

export interface ChatSourcesEvent {
  sources: ChatSource[]
}

export interface ChatDoneEvent {
  message_id: string
  tokens_used?: number | null
  response_time?: number | null
  model_name?: string | null
}

export interface ChatErrorEvent {
  code?: string
  message?: string
}

// ---------------------------------------------------------------------------
// HR Agent（app/schemas/agent.py，字段与后端 JSON 快照一致，全部 snake_case）
// ---------------------------------------------------------------------------

/** 任务状态；created / running / waiting_confirm 为未结束状态。 */
export type AgentTaskStatus =
  'created' | 'running' | 'waiting_confirm' | 'completed' | 'failed' | 'cancelled'

/** 步骤状态。 */
export type AgentStepStatus =
  'pending' | 'running' | 'waiting_confirm' | 'completed' | 'failed' | 'skipped' | 'cancelled'

/** 确认动作：执行 / 取消整个任务。 */
export type AgentConfirmAction = 'confirm' | 'cancel'

/** 一个步骤的执行快照。 */
export interface AgentStep {
  step_index: number
  tool: string
  name: string
  status: AgentStepStatus
  args: Record<string, unknown>
  summary: string
  result_preview: string | null
  content: string | null
  error: string | null
  editable: boolean
}

/** 待人工确认的写操作（确认卡片数据源）。 */
export interface AgentConfirm {
  step_index: number
  tool: string
  name: string
  summary: string
  args: Record<string, unknown>
  editable: boolean
}

/** 任务详情：SSE 首帧与刷新恢复共用。 */
export interface AgentTaskRead {
  id: string
  conversation_id: string
  status: AgentTaskStatus
  instruction: string
  current_step_index: number
  steps: AgentStep[]
  pending_confirm: AgentConfirm | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface AgentChatPayload {
  conversation_id: string
  content: string
}

export interface AgentChatResponse {
  task_id: string
  status: AgentTaskStatus
}

export interface AgentConfirmPayload {
  task_id: string
  action: AgentConfirmAction
  /** 确认时提交的修改后参数；缺省沿用原参数。 */
  params?: Record<string, unknown>
}

export interface AgentConfirmResponse {
  task_id: string
  status: AgentTaskStatus
}

/** 确认表单内上传简历的响应（只解析，不评分）。 */
export interface AgentResumeUploadResponse {
  upload_id: string
  filename: string
  resume_chars: number
}

/** GET /agent/stream/{task_id} 的事件载荷。 */
export interface AgentTaskStartedEvent {
  task: AgentTaskRead
}

export interface AgentStepEvent {
  step: AgentStep
}

export interface AgentMessageEvent {
  text: string
  step_index: number
}

export interface AgentConfirmRequiredEvent {
  task_id: string
  pending_confirm: AgentConfirm
}

export interface AgentTaskEndEvent {
  task_id: string
  status: AgentTaskStatus
  error: string | null
}
