# AGENTS.md

HR-Agent：AI 人力资源助手。后端 FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 17/pgvector；前端 Vue 3 + Vite + Element Plus + Pinia + ECharts（`frontend/`）。

## 后端常用命令（均在 backend/ 下执行）

- 依赖统一用 **uv**（不要用 pip）；首次执行 `uv sync`。
- 启动：`uv run uvicorn app.main:app --reload --port 18080`（文档 `/docs`，接口前缀 `/api/v1`）。
- 测试：`uv run pytest`；集成测试需数据库：`uv run pytest --run-integration`。
- 质量：`uv run black .`、`uv run isort .`、`uv run flake8 app tests`、`uv run mypy app`。
- 数据库：仓库根执行 `docker compose up -d`（宿主端口 5433）；初始化表与测试账号：`uv run python scripts/init_db.py`（`testuser / test123`）。
- 迁移：`uv run alembic upgrade head`；生成迁移：`uv run alembic revision --autogenerate -m "..."`。

## 前端常用命令（均在 frontend/ 下执行）

- 依赖统一用 **pnpm**；首次执行 `pnpm install`。
- 启动：`pnpm dev`（<http://127.0.0.1:5173>，`/api` 代理到后端 18080）。
- 质量：`pnpm type-check`、`pnpm lint`、`pnpm build`（提交前至少全部通过）。
- Element Plus 组件与 `ElMessage` 自动按需引入；生成文件 `src/auto-imports.d.ts`、`src/components.d.ts` 需提交。
- 新增 ECharts 图表类型时在 `src/plugins/echarts.ts` 注册，统一用 `BaseChart` 渲染。

## 代码规则

- 分层：`app/api/v1/endpoints/*` 只做参数校验、调用 service、组装响应；业务逻辑放 `app/services/*_service.py`；新路由注册到 `app/api/v1/router.py`。
- 错误：抛 `app/core/exceptions.py` 中的异常；新错误码加到 `error_codes.py`；不要手写错误响应（全局处理器统一格式）。
- 登录态：用 `app/api/deps.py` 的 `CurrentUser`，不要再自行解析 `Authorization`。
- 配置：只读 `app.core.config.settings`，禁止直接读环境变量。
- 数据库：接口使用 `get_db` 的 AsyncSession；查询关联必须显式预加载（如 `selectinload`），否则异步下会 `MissingGreenlet`。
- 模型：继承 `app.db.base.BaseModel`；新模型必须在 `app/db/models/__init__.py` 导入，否则 Alembic 发现不了。
- 当前**有意不建数据库外键**，关联完整性由业务层保证，不要擅自补 FK。
- Schema 放 `app/schemas/`；响应模型禁止暴露 `hashed_password`。
- 时间统一 UTC（`datetime.now(UTC)`）；行宽 100。

## 数据库与依赖

- 应用用 asyncpg；Alembic / 脚本用同步 psycopg，不要把同步会话用于异步接口。
- `DATABASE_URL` 里的 `+psycopg` 会自动转 asyncpg；本机密码见 `backend/.env`，需与根 `.env` 一致。
- `requirements.txt` 由 uv.lock 导出，禁止手改；依赖变更用 `uv add` / `uv remove`。
- 不提交 `.env`、`logs/`、`.venv/`、`__pycache__/`。

## 测试

- 默认测试不依赖外部服务；依赖 DB / Redis / LLM 的用例加 `@pytest.mark.integration`。
- 假会话与用户工厂在 `tests/fakes.py`；pytest-asyncio 为 auto 模式。
- 完成前至少通过：pytest、flake8、mypy（pre-commit 还会跑 black / isort）。

## 维护

- 本文件只保留高频、易错、影响执行的规则；细节见 `backend/README.md`、`frontend/README.md`。
- 迭代原则：同类问题重复出现才补充，避免罗列清单、防止膨胀。
