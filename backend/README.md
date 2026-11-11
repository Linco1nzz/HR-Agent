# HR-Agent 后端（backend）

FastAPI + SQLAlchemy 2 + Alembic + LangChain / LangGraph，依赖与虚拟环境由 **uv** 管理。
数据库为 PostgreSQL 17 + pgvector（由仓库根目录的 `docker-compose.yml` 启动）。

## 技术栈

| 用途 | 选型 |
| --- | --- |
| Web 框架 | FastAPI、Uvicorn |
| ORM / 迁移 | SQLAlchemy 2、Alembic（asyncpg 异步查询 / psycopg 同步迁移） |
| AI 编排 | LangChain、LangGraph、langchain-postgres、OpenAI、DashScope |
| HR 工作流 | Dify（Chatflow / advanced-chat，本地部署） |
| 任务队列 / 调度 | Celery + Redis、APScheduler |
| 配置 / 日志 | pydantic-settings、structlog |
| 测试 / 质量 | pytest、pytest-asyncio、black、isort、flake8、mypy、pre-commit |
| 文档解析 | pdfplumber、python-docx、openpyxl、pandas |

## 目录结构

```
backend/
├── pyproject.toml          # 依赖与工具配置（唯一事实来源）
├── uv.lock                 # 锁定版本，需要提交
├── .python-version         # Python 3.12
├── .venv/                  # uv 创建（已 gitignore）
├── .env.example / .env     # 应用配置（.env 已 gitignore）
├── requirements.txt        # 由 uv.lock 导出的运行时依赖（勿手改）
├── alembic.ini
├── migrations/             # Alembic 迁移脚本
├── app/
│   ├── main.py             # FastAPI 入口与 lifespan
│   ├── core/               # config/logging/security（密码哈希 + JWT）、异常体系、请求上下文中间件
│   ├── schemas/            # Pydantic 模型（error/auth/user/ai/jd/scoring_criteria.py）
│   ├── db/                 # session.py、base.py、models/
│   ├── services/           # 业务服务层（auth/user/dify_service/jd_service/scoring_criteria_service.py）
│   └── api/                # deps.py（当前登录用户 / Dify 客户端依赖）、v1/router.py 与 v1/endpoints/
└── tests/                  # pytest；集成测试需 --run-integration
```

## 快速开始

前置：uv（>= 0.13）、Docker Desktop。Python 3.12 由 uv 自动使用（本机已有则直接复用）。

```bash
cd backend

# 1. 创建 .venv 并按 uv.lock 安装依赖
uv sync

# 2. 准备环境变量（Windows PowerShell 用 Copy-Item）
cp .env.example .env
# 编辑 .env：DATABASE_URL 里的密码需与仓库根目录 .env 的 POSTGRES_PASSWORD 一致

# 3. 在仓库根目录启动数据库（宿主机端口 5433）
docker compose up -d

# 4. 启动开发服务器
uv run uvicorn app.main:app --reload --port 18080
```

启动后：

- Swagger 文档：<http://127.0.0.1:18080/docs>
- 存活探针：<http://127.0.0.1:18080/api/v1/health>
- 就绪探针（会查库）：<http://127.0.0.1:18080/api/v1/health/ready>

> 本仓库的 `backend/.env` 已按根目录 `.env` 中的密码生成；换机器或改密码后重新复制并修改。

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 安装/同步依赖 | `uv sync`（CI 用 `uv sync --frozen`） |
| 新增依赖 | `uv add <包名>`（自动写入 pyproject 并更新 lock） |
| 移除依赖 | `uv remove <包名>` |
| 运行任意命令 | `uv run <命令>`（无需手动激活 `.venv`） |
| 单元测试 | `uv run pytest` |
| 集成测试（需数据库） | `uv run pytest --run-integration` |
| 覆盖率 | `uv run pytest --cov=app --cov-report=term-missing` |
| 格式化 | `uv run black .`、`uv run isort .` |
| 静态检查 | `uv run flake8 app tests`、`uv run mypy app` |
| 安装提交钩子 | 在仓库根执行 `uv run --project backend pre-commit install -c backend/.pre-commit-config.yaml` |

## 数据库迁移（Alembic）

已内置一条空的 baseline 迁移，数据库可用时 `uv run alembic upgrade head` 即可验证连通性。

```bash
uv run alembic revision --autogenerate -m "create candidates table"  # 按模型生成迁移
uv run alembic upgrade head                                           # 应用迁移
uv run alembic downgrade -1                                           # 回退一步
uv run alembic current                                                # 当前版本
```

约定：

- ORM 模型放在 `app/db/models/`，并在 `app/db/models/__init__.py` 中导入；`migrations/env.py`
  已导入该包，`--autogenerate` 才能发现新表。
- 迁移与 `langchain-postgres` 使用同步 psycopg 连接；HTTP 请求的异步引擎使用 asyncpg。
  原因是 psycopg 3 的异步模式不支持 Windows 默认的 `ProactorEventLoop`。

## 异常处理

全局异常处理由以下模块组成：

| 模块 | 职责 |
| --- | --- |
| `app/core/error_codes.py` | 统一错误码 `ErrorCode` 与 HTTP 状态码 → 错误码的默认映射 |
| `app/core/exceptions.py` | 项目自定义异常基类 `AppException` 与常用子类（400 / 401 / 403 / 404 / 409 / 422 / 429 / 5xx） |
| `app/core/exception_handlers.py` | 各类异常 → 统一错误响应的转换，`register_exception_handlers()` 在 `create_app()` 中注册 |
| `app/core/middleware.py` | `RequestContextMiddleware`：生成 / 透传 `X-Request-ID`，并绑定日志上下文 |
| `app/schemas/error.py` | 错误响应模型 `ErrorResponse` / `FieldError`（可直接用于 OpenAPI） |

### 统一错误响应

所有异常（框架内置 404/405、参数校验、数据库错误与未知异常）都返回同一结构：

```json
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "details": {
    "errors": [
      {
        "field": "body.email",
        "message": "value is not a valid email address",
        "type": "value_error"
      }
    ]
  },
  "request_id": "e23358f43b3b476381834bb857b089db",
  "timestamp": "2026-11-06T04:10:22.568394Z"
}
```

- `code`：稳定错误码，前端据此做分支，取值见 `app/core/error_codes.py`。
- `message`：可直接展示给用户的说明。
- `details`：可选上下文；数据库 / 响应校验等内部细节，以及 5xx 自定义异常的 `details`，
  只在非生产环境返回。
- `request_id`：请求追踪 ID，同时写入响应头 `X-Request-ID`；客户端传入合法同名请求头时原样沿用。
- `timestamp`：错误发生时间（UTC）。

### 异常类型与状态码映射

| 异常 | HTTP | 错误码 | 说明 |
| --- | --- | --- | --- |
| `AppException` 及子类 | 异常类声明的 `status_code` | 异常类声明的 `code` | 业务代码主动抛出；WebSocket 场景以 1008 / 1011 关闭连接 |
| `HTTPException`（FastAPI / Starlette） | 原状态码 | 按状态码映射，如 `NOT_FOUND` | 保留响应头；未自定义 `detail` 时使用中文默认文案 |
| `WebSocketException` | 异常指定的 close code | — | 按指定 code 关闭连接 |
| `RequestValidationError` | 422 | `VALIDATION_ERROR` | `details.errors` 给出字段级错误，不包含原始输入 |
| `ResponseValidationError` | 500 | `RESPONSE_VALIDATION_ERROR` | 服务端返回不符合 `response_model` |
| `WebSocketRequestValidationError` | WS 1008 | — | 关闭 WebSocket 连接 |
| `IntegrityError` | 409 | `DATABASE_CONFLICT` | 唯一约束 / 外键 / 非空等冲突 |
| `OperationalError` | 503 | `DATABASE_UNAVAILABLE` | 连接失败、连接中断 |
| `sqlalchemy.exc.TimeoutError` | 503 | `DATABASE_TIMEOUT` | 连接池获取连接超时 |
| `NoResultFound` | 404 | `NOT_FOUND` | `one()` / `scalar_one()` 未查到数据 |
| `MultipleResultsFound` | 500 | `DATABASE_ERROR` | 期望唯一结果却返回多条 |
| 其他 `SQLAlchemyError` | 500 | `DATABASE_ERROR` | 数据库异常兜底 |
| 其他未捕获异常 | 500 | `INTERNAL_ERROR` | 完整堆栈只写日志，客户端只看到通用文案 |

### 在业务代码中使用

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import User


async def get_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在", details={"user_id": str(user_id)})
    return user


async def create_user(db: AsyncSession, email: str) -> User:
    if await db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("邮箱已被注册", details={"field": "email"})
    ...
```

新增业务异常：继承 `AppException` 并声明 `status_code` / `code` / `default_message`；
新错误码同时加入 `ErrorCode`。只有需要特殊响应格式时才新增处理器。

日志约定：4xx 记 `warning`，5xx 记 `error` 并附堆栈；每条日志自动带上
`request_id`、`method`、`path`，可与错误响应中的 `request_id` 对应排查。

> 需要精确控制状态码或响应头（如 401 的 `WWW-Authenticate`）时仍可直接抛
> `HTTPException`，它同样会走统一响应格式。

### 在 OpenAPI 中声明错误响应（可选）

```python
from app.schemas.error import ErrorResponse

@router.post(
    "/users",
    responses={409: {"model": ErrorResponse, "description": "邮箱已注册"}},
)
async def create_user(...): ...
```

## 登录与鉴权

登录接口返回 JWT 访问令牌，受保护接口通过 `Authorization: Bearer <token>` 访问。

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/login` | 用户名或邮箱 + 密码登录，返回令牌与用户信息 | 否 |
| `GET` | `/api/v1/auth/me` | 获取当前登录用户 | 是 |
| `POST` | `/api/v1/auth/logout` | 退出登录（JWT 无状态，仅记录日志，客户端需删除本地令牌） | 是 |

### 登录示例

```bash
curl -X POST http://127.0.0.1:18080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "test123"}'
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "cce3c976-cba8-40c8-8529-e55d669a5074",
    "username": "testuser",
    "email": "testuser@example.com",
    "full_name": "Test Administrator",
    "phone": null,
    "department": null,
    "position": null,
    "employee_id": null,
    "is_superuser": true,
    "is_verified": true,
    "is_active": true,
    "bio": null,
    "avatar_url": null,
    "last_login": "2026-11-06T10:37:18.251424Z",
    "roles": ["超级管理员"]
  }
}
```

后续请求携带令牌：

```bash
curl http://127.0.0.1:18080/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### 认证相关错误码

| HTTP | 错误码 | 说明 |
| --- | --- | --- |
| 401 | `INVALID_CREDENTIALS` | 用户名或密码错误（账号不存在与密码错误返回同一错误码，避免账号枚举） |
| 401 | `INVALID_TOKEN` | 未携带令牌、令牌格式 / 签名非法，或令牌对应用户已不存在 |
| 401 | `TOKEN_EXPIRED` | 令牌已过期，需要重新登录 |
| 403 | `ACCOUNT_DISABLED` | 账号已被停用 |

401 响应都会带上 `WWW-Authenticate: Bearer`。令牌默认有效期由
`ACCESS_TOKEN_EXPIRE_MINUTES` 控制（默认 1440 分钟），载荷包含 `sub`（用户 ID）、
`iat` / `exp`、`jti` 与 `type`。`JWT_SECRET` 生产环境必须替换为不少于 32 字节的随机字符串。

### 在业务接口中要求登录

```python
from fastapi import APIRouter

from app.api.deps import CurrentUser

router = APIRouter()


@router.get("/profile")
async def read_profile(current_user: CurrentUser) -> dict[str, str]:
    return {"username": current_user.username}
```

`CurrentUser` 会自动校验 Bearer 令牌、加载用户（含角色）并检查账号是否启用；
需要角色 / 权限判断时可在此基础上继续扩展依赖。

## JD 管理

JD（职位描述）保存于 `job_description` 表，技能列表与附加元数据使用 PostgreSQL
`JSONB`。前端页面为 `/jds`，支持列表、详情、新建、AI 生成、编辑与状态筛选。

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/jds` | 分页列表，支持 `keyword` / `status` | 是 |
| `POST` | `/api/v1/jds` | 保存手动填写或 AI 生成的 JD | 是 |
| `GET` | `/api/v1/jds/{id}` | 详情（含完整正文、技能、生成信息） | 是 |
| `PATCH` | `/api/v1/jds/{id}` | 局部编辑 | 是 |
| `POST` | `/api/v1/jds/generate` | 调用 Dify type=1 阻塞生成 JD，**不落库** | 是 |
| `POST` | `/api/v1/jds/generate/stream` | 流式生成 JD（SSE），**不落库** | 是 |

列表项额外返回 `criteria_count`，表示该 JD 已关联的评分标准数量。

字段与 `app/schemas/jd.py` 对齐：`title` / `content` 必填，`department`、
`location`、`salary_range`、`experience_level`、`education`、`job_type`、
`skills`、`requirements`、`status`、`meta_data`、`conversation_id`、
`workflow_type` 可选。`status` 取值为 `draft` / `generated` / `published` /
`archived`，默认 `draft`。

生成流程：前端提交表单 → `POST /jds/generate/stream` → 后端调用
`dify_service.stream_chat(type=1)`，解析 Dify SSE 后归一化为：

| 事件 | data | 说明 |
| --- | --- | --- |
| `start` | `{"workflow_type":"jd_generation"}` | 流已建立 |
| `delta` | `{"content":"..."}` | 增量文本 |
| `done` | `GenerateJDResponse` | 完整 `content` / `conversation_id` / `usage` |
| `error` | `{"status","code","message"}` | 流式阶段的 Dify / 超时错误 |

前端用 `fetch` + `ReadableStream` 边收边渲染，收到 `done` 后再调用
`POST /jds`（或 `PATCH /jds/{id}`）落库。阻塞接口
`POST /jds/generate` 仍保留，供不需要流式的调用方使用。生成接口的 Dify 错误
沿用 [错误码](#错误码) 中的 `DIFY_*`。

首次部署或拉取代码后执行：

```bash
uv run alembic upgrade head
```

## 简历评分标准

评分标准保存于 `scoring_criteria` 表，正文 `content` 为 Markdown，结构化评分维度
`scoring_dimensions` 与附加数据 `criteria_data` 使用 `JSONB`。`job_description_id`
记录来源 JD，按项目约定不建数据库外键，由服务层校验关联 JD 是否存在。

评分标准已整合进 JD 管理页 `/jds`：打开某个 JD 后切换到「简历评分标准」标签，
即可查看该 JD 已有的评分标准、AI 生成新标准并进入编辑；左侧 JD 列表会显示每个
岗位已关联的评分标准数量。旧的 `/scoring-criteria` 入口会重定向回 `/jds`。

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/scoring-criteria` | 分页列表，支持 `keyword` / `status` / `job_description_id` | 是 |
| `POST` | `/api/v1/scoring-criteria` | 保存手动编辑或 AI 生成的评分标准 | 是 |
| `GET` | `/api/v1/scoring-criteria/{id}` | 详情（含正文、维度、生成信息） | 是 |
| `PATCH` | `/api/v1/scoring-criteria/{id}` | 局部编辑 | 是 |
| `POST` | `/api/v1/scoring-criteria/generate` | 根据已有 JD 调用 Dify type=2 生成，**不落库** | 是 |
| `POST` | `/api/v1/scoring-criteria/generate/stream` | 流式生成评分标准（SSE），**不落库** | 是 |

生成请求体：

```json
{
  "job_description_id": "JD 的 UUID",
  "title": "可选标题，省略时使用「JD 标题 - 简历评分标准」",
  "total_score": "100",
  "instructions": "可选的额外生成要求"
}
```

后端会加载 JD 并把职位名称、部门、地点、经验 / 学历要求、技能、正文与职位要求
拼成 `query`，调用 Dify Chatflow type=2；返回 `title` / `job_title` / `content` /
`total_score` / `job_description_id` / `conversation_id` / `workflow_type` 等字段。
生成结果不自动落库，前端编辑后调用创建接口保存。JD 不存在时返回 `404`，Dify
错误沿用 [错误码](#错误码) 中的 `DIFY_*`。

`/generate/stream` 与阻塞接口入参相同，把 Dify SSE 归一化为：

| 事件 | data | 说明 |
| --- | --- | --- |
| `start` | `{"workflow_type":"scoring_criteria_generation"}` | 流已建立 |
| `delta` | `{"content":"..."}` | 增量文本 |
| `done` | `GenerateScoringCriteriaResponse` | 完整评分标准与生成信息 |
| `error` | `{"status","code","message"}` | 流式阶段的 Dify / 超时错误 |

前端用 `fetch` + `ReadableStream` 边收边渲染，收到 `done` 后再调用创建接口保存。

字段与 `app/schemas/scoring_criteria.py` 对齐：`title` / `content` 必填，
`job_title`、`criteria_data`、`total_score`、`scoring_dimensions`、`status`、
`meta_data`、`conversation_id`、`workflow_type`、`job_description_id` 可选。
`status` 取值为 `draft` / `generated` / `published` / `archived`，默认 `draft`。

## 简历筛选

简历评分记录保存于 `resume_evaluation` 表：一次上传对应一条记录，保存文件信息、
解析后的简历正文、AI 提取的候选人信息、评分维度与总分。`job_description_id` /
`scoring_criteria_id` 按项目约定不建数据库外键，上传时由业务层校验。

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/resume-evaluations` | 分页列表，支持 `keyword` / `status` / `job_description_id` | 是 |
| `POST` | `/api/v1/resume-evaluations/upload` | 上传简历并按 JD 评分标准评分 | 是 |
| `GET` | `/api/v1/resume-evaluations/{id}` | 详情（候选人信息、简历正文、总分与维度） | 是 |
| `PATCH` | `/api/v1/resume-evaluations/{id}/status` | 人工更新复核状态 | 是 |

上传使用 `multipart/form-data`：

```bash
curl -X POST http://127.0.0.1:18080/api/v1/resume-evaluations/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@resume.pdf" \
  -F "job_description_id=<JD UUID>"
```

- 支持 PDF / DOC / DOCX / TXT，默认单文件不超过 10MB；分别由
  `RESUME_UPLOAD_DIR`、`RESUME_MAX_FILE_SIZE_MB` 配置。
- 评分必须指定 JD，且该 JD 至少有一份启用中的评分标准；后端取最近更新的一份。
  没有评分标准时返回 `422 SCORING_CRITERIA_REQUIRED`，不会调用 AI。
- 调用 Dify Chatflow type=3：`query` 为评分标准正文，`inputs.jianli` 为解析后的
  简历文本，`inputs.jobName` 为 JD 标题。
- 评分完成即保存记录，默认状态 `pending`（待复核）；HR 可改为 `interview`
  （进入面试）或 `rejected`（已淘汰）。AI 评分只作为初筛参考。
- 文件格式 / 大小 / 解析错误分别返回 `UNSUPPORTED_RESUME_FORMAT` /
  `RESUME_FILE_TOO_LARGE` / `RESUME_PARSE_FAILED`。
- 旧版 DOC 解析依赖系统工具：优先 antiword、catdoc、LibreOffice，Windows 上
  还会尝试本机 Word COM；都没有时会提示另存为 DOCX。

## Dify Chatflow 接入

HR 业务工作流部署在本地 Dify，应用 `hr_agent` 为 **advanced-chat（Chatflow）**，
不是 Workflow 类型，因此后端调用 `POST /v1/chat-messages`，而不是
`POST /v1/workflows/run`。Chatflow 开始节点用数字变量 `type` 分支：

| type | 流程 | query 含义 | 必填 inputs |
| --- | --- | --- | --- |
| `1` | JD 生成 | 岗位需求 / 招聘要求 | — |
| `2` | 简历评价标准 | JD 内容 | — |
| `3` | 简历评价 | 简历评价标准（通常来自 type=2） | `jianli` |
| `4` | 面试方案 | 可选补充说明（省略时后端补默认 query） | `jd`、`jianli` |
| `5` | 试卷生成 | 试卷要求（题型 / 数量 / 分值） | `fileContent` |
| `6` | 阅卷评分 | 用户试卷内容（JSON） | — |

### 接口

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ai/types` | 返回上述类型及每个类型的入参契约 | 是 |
| `GET` | `/api/v1/ai/parameters` | 代理 Dify `GET /v1/parameters`，含输入表单 / 开场白 | 是 |
| `POST` | `/api/v1/ai/chat` | 阻塞调用，等 Dify 完整生成后返回 | 是 |
| `POST` | `/api/v1/ai/chat/stream` | SSE 流式调用，透传 Dify 事件 | 是 |

请求体（阻塞 / 流式相同）：

```json
{
  "type": 1,
  "query": "招聘一名前端工程师，3 年以上经验",
  "inputs": {},
  "conversation_id": null,
  "auto_generate_name": true
}
```

- `type` 必填，取值 1–6；`inputs` 中的 `type` 会被顶层值覆盖。
- `query` 在 type=1/2/3/5/6 时必填；type=4 可为空，后端会补一个默认 query
  以满足 Dify `/chat-messages` 对 `query` 非空的要求（该分支实际只使用 `jd` / `jianli`）。
- `conversation_id` 首次省略，后续传入上一次响应中的值即可延续多轮会话。
- `files` 可透传 Dify 文件对象；当前流程使用文本变量 `fileContent`，不依赖二进制上传。

### 调用示例

```bash
TOKEN="<access_token>"

# 阻塞：生成 JD
curl -X POST http://127.0.0.1:18080/api/v1/ai/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type": 1, "query": "招聘一名前端工程师，3 年以上经验"}'

# 流式：浏览器 / fetch 读取 text/event-stream
curl -N -X POST http://127.0.0.1:18080/api/v1/ai/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type": 4, "inputs": {"jd": "...", "jianli": "..."}}'
```

流式响应的每个 `data:` 行都是 JSON，事件类型在 `event` 字段中，可能是
`workflow_started`、`node_started`、`node_finished`、`message`、`message_end`、
`workflow_finished`。流式阶段无法再改 HTTP 状态码，因此 Dify 4xx/5xx、超时、
断连会以错误事件返回：

```text
data: {"event":"error","status":503,"code":"DIFY_UNAVAILABLE","message":"..."}
```

JD、简历评分标准等需要把增量文本重组为完整业务对象的接口，统一由
`app/services/streaming.py` 的 `stream_chatflow` 编排 `start` / `delta` /
`done` / `error`，接口层用 `app/api/v1/responses.py` 的 `sse_response` 返回。
新增生成流程只需提供 `ChatRequest`、`done` 事件的响应组装函数和错误文案。

### 错误码

| HTTP | 错误码 | 说明 |
| --- | --- | --- |
| 422 | `WORKFLOW_VALIDATION_ERROR` | 当前 type 缺少 query / 必填 inputs，或输入超过长度限制 |
| 422 | `DIFY_INVALID_PARAM` | Dify 判定参数不合法 |
| 502 | `DIFY_UNAUTHORIZED` | `DIFY_API_KEY` 无效或无应用权限 |
| 502 | `DIFY_WORKFLOW_FAILED` | Dify 工作流执行失败 |
| 502 | `DIFY_INVALID_RESPONSE` | Dify 返回非 JSON / 缺少 `answer` |
| 503 | `DIFY_NOT_CONFIGURED` | 未配置 `DIFY_API_KEY` |
| 503 | `DIFY_UNAVAILABLE` | Dify 不可达、超时或返回 5xx |

### 常见问题

- `type=3` 返回 `DIFY_INVALID_PARAM`，且 `details.dify_message` 包含
  `Structured output validation failed`：当前 Dify 的 `LLM 3` 节点启用了结构化输出，
  但 schema 是空对象（`additionalProperties: false`），模型输出必然校验失败。
  在 Dify 工作流中关闭该节点的“结构化输出”，或补全与实际 JSON 输出匹配的 schema
  后重新发布即可；后端会把该错误转换为“关闭 LLM 3 结构化输出”的可操作提示。

### 本地 Dify 地址说明

本机 Dify 的 `api` 容器只暴露容器内 `5001`，宿主机未发布该端口，直接访问
`http://127.0.0.1:5001/v1` 会失败。当前通过 Dify nginx 的 `http://127.0.0.1/v1`
接入；若要让 5001 直连，可在 Dify 的 `docker-compose.yaml` 中为 `api` 服务增加
`5001:5001` 端口映射后重启，并把 `DIFY_BASE_URL` 改为
`http://127.0.0.1:5001/v1`。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | `development` / `testing` / `production` |
| `DEBUG` | `false` | 为 true 时 SQLAlchemy 打印 SQL |
| `LOG_LEVEL` | `INFO` | 日志级别；生产环境输出 JSON |
| `DATABASE_URL` | 本机 5433 的 hr_agent | SQLAlchemy 连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery / 缓存（暂无 redis 服务） |
| `JWT_SECRET` | `change-me-in-production-please-32bytes` | JWT 签名密钥；生产环境必须改为不少于 32 字节的随机字符串 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | 访问令牌有效期（分钟） |
| `ARGON2_TIME_COST` / `ARGON2_MEMORY_COST` / `ARGON2_PARALLELISM` | `2` / `32768` / `2` | Argon2id 参数（内存单位 KiB） |
| `LLM_API_KEY` / `LLM_BASE_URL` | 空 | 大模型密钥与代理地址 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `text-embedding-3-small` / `1536` | 向量模型与维度 |
| `DIFY_BASE_URL` | `http://127.0.0.1/v1` | Dify API 地址，必须包含 `/v1` |
| `DIFY_API_KEY` | 空 | Dify 应用「API 访问」密钥（`app-` 开头） |
| `DIFY_TIMEOUT_SECONDS` / `DIFY_CONNECT_TIMEOUT_SECONDS` | `120` / `5` | 工作流读取超时 / 连接超时（秒） |
| `RESUME_UPLOAD_DIR` | `backend/uploads/resumes` | 简历附件保存目录 |
| `RESUME_MAX_FILE_SIZE_MB` | `10` | 单份简历最大体积（MB） |
| `CORS_ORIGINS` | 本地前端 5173 | 逗号分隔的允许来源 |

## 依赖源说明

`pyproject.toml` 的 `[[tool.uv.index]]` 默认指向清华 PyPI 镜像以加速国内下载。
如需改用 PyPI 官方源：删除该段后重新执行 `uv lock`。

`requirements.txt` 是从 `uv.lock` 导出的运行时依赖快照（供 Docker / pip 场景使用），
请勿手动编辑；依赖变更请通过 `uv add` / `uv remove` 修改 `pyproject.toml`。

## 开发约定

- 新接口：在 `app/api/v1/endpoints/<domain>.py` 定义，并注册到 `app/api/v1/router.py`。
- 业务逻辑放在 `app/services/<domain>_service.py`，接口层只做参数校验、调用服务与组装响应；
  例如登录流程在 `app/services/auth_service.py`，用户查询在 `app/services/user_service.py`。
- 业务异常统一抛 `app/core/exceptions.py` 中的异常（如 `NotFoundError`、`ConflictError`），
  不要在每个接口里手写错误响应；确需精确控制状态码 / 响应头时可用 `HTTPException`。
- 配置统一通过 `app.core.config.settings` 读取，不要直接读 `os.environ`。
- 默认测试不依赖外部服务；依赖 PostgreSQL / Redis / LLM 的测试加 `@pytest.mark.integration`。
- 提交前安装 pre-commit（在仓库根执行上面的安装命令）；钩子会运行 black、isort、flake8 等检查，
  任一项失败会中止提交，必要时可用 `git commit --no-verify` 临时跳过。
