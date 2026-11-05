# PostgreSQL + pgvector（Docker 部署说明）

本目录配合仓库根目录的 `docker-compose.yml`，为 HR-Agent 提供本地开发用数据库：
**PostgreSQL 17 + pgvector**（Docker 官方 `pgvector/pgvector` 镜像）。

## 目录结构

```
HR-Agent/
├── docker-compose.yml          # 数据库服务定义
├── .env                        # 本地配置（含密码，已 gitignore）
├── .env.example                # 配置模板
├── docker/
│   ├── README.md               # 本文件
│   └── postgres/initdb/
│       └── 01-extensions.sql   # 首次启动自动安装扩展
├── backend/                    # 后端服务（自行接入数据库）
└── frontend/                   # 前端服务
```

## 前置条件

- Docker Desktop 已启动（Windows 下需 WSL2 后端）
- 宿主机端口未被占用。**本机 5432 已被原生 PostgreSQL 16 服务
  (`postgresql-x64-16`) 占用，因此 `.env` 中 `POSTGRES_PORT=5433`**。
  如需改用其他端口，修改 `.env` 的 `POSTGRES_PORT` 后 `docker compose up -d`。

## 启动

```bash
# 1. 首次使用：复制配置并修改密码
cp .env.example .env

# 2. 启动（会自动拉取镜像）
docker compose up -d

# 3. 等待健康检查通过（STATUS 显示 healthy）
docker compose ps
```

查看初始化日志，确认扩展已安装：

```bash
docker compose logs pg | grep -E "vector|extension|ready to accept"
```

## 连接信息

| 场景 | 连接串 |
| --- | --- |
| 宿主机（本机跑 backend） | `postgresql://hr_agent_user:<PASSWORD>@localhost:5433/hr_agent` |
| 同 compose 网络的容器 | `postgresql://hr_agent_user:<PASSWORD>@pg:5432/hr_agent` |

- 用户名：`hr_agent_user`；密码：`.env` 中的 `POSTGRES_PASSWORD`；库名：`hr_agent`
- 宿主机端口：`.env` 中的 `POSTGRES_PORT`（当前为 `5433`）
- 时区：`Asia/Shanghai`
- 编码：`UTF8`

按技术栈拆分的配置项（把 `<PASSWORD>` 换成 `.env` 里的真实密码）：

```ini
# backend/.env（Python SQLAlchemy 示例）
DATABASE_URL=postgresql+psycopg://hr_agent_user:<PASSWORD>@localhost:5433/hr_agent

# backend/.env（Node Prisma 示例）
DATABASE_URL="postgresql://hr_agent_user:<PASSWORD>@localhost:5433/hr_agent?schema=public"
```

> 密码请以自己 `.env` 中的值为准。
>
> 两个 `.env` 的分工：根目录 `.env` 只给 `docker compose` 做变量插值（DB 账号、端口、调优）；
> 后端应用读的是 `backend/.env`，模板见 `backend/.env.example`。

## 验证 pgvector

```bash
# 进入 psql
docker compose exec pg psql -U hr_agent_user -d hr_agent
```

```sql
-- 查看已安装扩展
\dx

-- 版本与向量能力
SELECT extversion FROM pg_extension WHERE extname = 'vector';

-- 建表 + HNSW 索引示例
CREATE TABLE IF NOT EXISTS demo_embedding (
    id        bigserial PRIMARY KEY,
    content   text,
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_demo_embedding_hnsw
    ON demo_embedding USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 近邻检索
INSERT INTO demo_embedding (content, embedding)
VALUES ('示例', array_fill(0.1, ARRAY[1536])::vector);

SELECT id, content, embedding <=> array_fill(0.1, ARRAY[1536])::vector AS distance
FROM demo_embedding
ORDER BY embedding <=> array_fill(0.1, ARRAY[1536])::vector
LIMIT 5;

-- 清理示例表
DROP TABLE demo_embedding;
```

`vector(1536)` 对应 OpenAI `text-embedding-3-small`；如使用 `bge-m3`（1024 维）等模型请相应调整维度。

## 常用运维命令

```bash
docker compose ps                 # 状态 / 健康检查
docker compose logs -f pg         # 实时日志
docker compose restart pg         # 重启
docker compose stop pg            # 停止（保留数据）
docker compose down               # 删除容器与网络（保留数据卷）
docker compose down -v            # 删除容器 + 数据卷（数据全部丢失）
```

## 数据备份与恢复

```bash
# 备份（导出到当前目录）
docker compose exec -T pg pg_dump -U hr_agent_user -d hr_agent -Fc > backup_$(date +%Y%m%d).dump

# 恢复
docker compose exec -T pg pg_restore -U hr_agent_user -d hr_agent --clean --if-exists < backup_20260101.dump
```

## 修改配置后如何生效

- 改 `.env` 中的**端口 / 数据库参数**后：`docker compose up -d` 会重建容器，立即生效。
- 改 `.env` 中的**账号或密码**后：`docker compose up -d` **不会**生效！
  `POSTGRES_USER` / `POSTGRES_PASSWORD` 只在数据卷为空时用于初始化。已有数据的处理方式：
  - 只改密码：进库执行 `ALTER USER hr_agent_user WITH PASSWORD '<新密码>';`
  - 改用户名：`CREATE ROLE <新用户> LOGIN SUPERUSER PASSWORD '<密码>';` 并调整库属主/授权，
    或直接 `docker compose down -v && docker compose up -d` 重建（会清空数据）。
- 改 `initdb/*.sql`：只在**首次初始化**执行。要重新初始化：
  `docker compose down -v && docker compose up -d`（会清空数据）。
- 改数据库参数（`shared_buffers` 等）：`docker compose up -d` 即可，参数来自 `command`。

## 让 backend / frontend 容器接入同一网络

后续把 backend 容器化时，在 `docker-compose.yml` 里加服务并加入 `hr_agent_net` 网络，
即可用主机名 `pg`、容器内端口 `5432` 访问数据库；此时**无需**向宿主机暴露端口。

```yaml
services:
  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@pg:5432/${POSTGRES_DB}
    networks:
      - hr_agent_net
    depends_on:
      pg:
        condition: service_healthy
```

## 排错

| 现象 | 处理 |
| --- | --- |
| `port is already allocated` | 改 `.env` 的 `POSTGRES_PORT`，或停掉占用该端口的服务 |
| 宿主机连 5432 报 `password authentication failed`，但容器内一切正常 | 本机原生 PostgreSQL 抢占了 5432（本机即 `postgresql-x64-16`）。用 `.env` 里的 `POSTGRES_PORT=5433` 连接，或停掉 `/ 改端口` 该服务 |
| 拉取镜像超时 | 配置 Docker Desktop 的 registry mirror（Settings → Docker Engine → `registry-mirrors`） |
| `password authentication failed` | 数据卷已用旧密码初始化，进库 `ALTER USER` 或 `down -v` 重建 |
| 改了账号密码但登录仍是旧账号 | `POSTGRES_USER` 只在首次初始化生效，需 `down -v` 重建或手动 `CREATE ROLE` |
| `\dx` 里没有 `vector`，日志显示 `ignoring /docker-entrypoint-initdb.d/*` | `docker/postgres/initdb/` 为空或脚本丢失（挂载空目录不会报错）。恢复 `01-extensions.sql` 后 `down -v && up -d` |
| 容器反复重启 | `docker compose logs pg` 查看，常见为宿主机磁盘满或数据卷损坏 |
| `extension "vector" is not available` | 镜像不是 `pgvector/pgvector`，检查 `PGVECTOR_IMAGE` |
