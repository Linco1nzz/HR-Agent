# HR-Agent 后端（backend）

FastAPI + SQLAlchemy 2 + Alembic + LangChain / LangGraph，依赖与虚拟环境由 **uv** 管理。
数据库为 PostgreSQL 17 + pgvector（由仓库根目录的 `docker-compose.yml` 启动）。

## 技术栈

| 用途 | 选型 |
| --- | --- |
| Web 框架 | FastAPI、Uvicorn |
| ORM / 迁移 | SQLAlchemy 2、Alembic（asyncpg 异步查询 / psycopg 同步迁移） |
| AI 编排 | LangChain、LangGraph、langchain-postgres、OpenAI、DashScope |
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
│   ├── core/               # config.py、logging.py
│   ├── db/                 # session.py、base.py、models/
│   └── api/v1/             # router.py 与 endpoints/（health.py）
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
uv run uvicorn app.main:app --reload --port 8000
```

启动后：

- Swagger 文档：<http://127.0.0.1:8000/docs>
- 存活探针：<http://127.0.0.1:8000/api/v1/health>
- 就绪探针（会查库）：<http://127.0.0.1:8000/api/v1/health/ready>

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

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | `development` / `testing` / `production` |
| `DEBUG` | `false` | 为 true 时 SQLAlchemy 打印 SQL |
| `LOG_LEVEL` | `INFO` | 日志级别；生产环境输出 JSON |
| `DATABASE_URL` | 本机 5433 的 hr_agent | SQLAlchemy 连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery / 缓存（暂无 redis 服务） |
| `JWT_SECRET` | `change-me-in-production` | 生产环境必须修改 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token 有效期 |
| `ARGON2_TIME_COST` / `ARGON2_MEMORY_COST` / `ARGON2_PARALLELISM` | `2` / `32768` / `2` | Argon2id 参数（内存单位 KiB） |
| `LLM_API_KEY` / `LLM_BASE_URL` | 空 | 大模型密钥与代理地址 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `text-embedding-3-small` / `1536` | 向量模型与维度 |
| `CORS_ORIGINS` | 本地前端 5173 | 逗号分隔的允许来源 |

## 依赖源说明

`pyproject.toml` 的 `[[tool.uv.index]]` 默认指向清华 PyPI 镜像以加速国内下载。
如需改用 PyPI 官方源：删除该段后重新执行 `uv lock`。

`requirements.txt` 是从 `uv.lock` 导出的运行时依赖快照（供 Docker / pip 场景使用），
请勿手动编辑；依赖变更请通过 `uv add` / `uv remove` 修改 `pyproject.toml`。

## 开发约定

- 新接口：在 `app/api/v1/endpoints/<domain>.py` 定义，并注册到 `app/api/v1/router.py`。
- 配置统一通过 `app.core.config.settings` 读取，不要直接读 `os.environ`。
- 默认测试不依赖外部服务；依赖 PostgreSQL / Redis / LLM 的测试加 `@pytest.mark.integration`。
- 提交前安装 pre-commit（在仓库根执行上面的安装命令）；钩子会运行 black、isort、flake8 等检查，
  任一项失败会中止提交，必要时可用 `git commit --no-verify` 临时跳过。
