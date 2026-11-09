# HR-Agent 前端（frontend）

HR-Agent 的 Web 界面：Vue 3 + TypeScript + Vite，使用 Element Plus 组件库、Pinia 状态管理、
Vue Router 路由和 ECharts 数据可视化。

## 技术栈

| 用途 | 选型                                                |
| ---- | --------------------------------------------------- |
| 框架 | Vue 3（`<script setup lang="ts">`）                 |
| 构建 | Vite 8、TypeScript 6、vue-tsc                       |
| UI   | Element Plus（按需加载）+ `@element-plus/icons-vue` |
| 状态 | Pinia（Setup Store 写法）                           |
| 路由 | Vue Router（history 模式）                          |
| 图表 | ECharts 6（按需注册图表类型）                       |
| 请求 | Axios（统一拦截器与错误类型）                       |
| 质量 | ESLint 10、Prettier                                 |

## 快速开始

前置：Node.js >= 20.19、pnpm，以及已启动的后端（默认 `http://127.0.0.1:18080`）。

```bash
cd frontend
pnpm install
pnpm dev
```

打开 <http://127.0.0.1:5173>。

开发环境的后端联调：

1. 在仓库根目录启动数据库：`docker compose up -d`。
2. 在 `backend/` 启动接口：`uv run uvicorn app.main:app --reload --port 18080`。
3. 如尚未初始化测试账号，执行 `uv run python scripts/init_db.py`。
4. 使用 `testuser / test123` 登录。

Vite 会把 `/api` 代理到 `http://127.0.0.1:18080`，因此浏览器侧没有跨域问题；
令牌、`401` 处理与路由守卫均已接好后端认证接口。

## 常用命令

| 目的         | 命令                                |
| ------------ | ----------------------------------- |
| 安装依赖     | `pnpm install`                      |
| 开发服务器   | `pnpm dev`（固定 5173 端口）        |
| 生产构建     | `pnpm build`（先跑 vue-tsc 再打包） |
| 预览构建产物 | `pnpm preview`（4173 端口）         |
| 类型检查     | `pnpm type-check`                   |
| 代码检查     | `pnpm lint` / `pnpm lint:fix`       |
| 格式化       | `pnpm format` / `pnpm format:check` |

## 目录结构

```
frontend/
├── src/
│   ├── api/                 # Axios 实例、认证 / JD 接口、后端 Schema 类型
│   ├── components/          # BaseChart、JdMarkdown、JdEditorDrawer
│   ├── layouts/             # 工作台布局（侧边栏 / 顶栏 / 内容区）
│   ├── plugins/             # echarts 按需注册
│   ├── router/              # 路由表、登录守卫、401 统一跳转
│   ├── stores/              # Pinia：会话与用户信息
│   ├── styles/              # 全局样式与 Element Plus 主题变量
│   ├── utils/               # localStorage 令牌读写、SSE 帧解析
│   ├── views/               # 登录、工作台、JD 管理、404
│   ├── App.vue              # ElConfigProvider + router-view
│   └── main.ts              # 应用入口
├── public/favicon.svg
├── .env.development         # 开发环境变量（提交）
├── .env.production          # 生产环境变量（提交）
├── vite.config.ts           # 别名、代理、Element Plus 按需加载、分包
├── eslint.config.js
└── tsconfig*.json
```

## 环境变量

| 变量                | 默认值                   | 说明                                       |
| ------------------- | ------------------------ | ------------------------------------------ |
| `VITE_API_BASE_URL` | `/api/v1`                | Axios 的 `baseURL`；生产环境通常与前端同源 |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:18080` | 仅开发服务器使用，`/api` 代理目标          |

`.env.development` / `.env.production` 已提交，便于团队开箱即用；个人覆盖请新建
`.env.development.local`（已被 gitignore）。所有 `VITE_*` 变量都会打进客户端产物，禁止放密钥。

## 后端对接约定

- 接口前缀 `/api/v1`，类型定义在 `src/api/types.ts`，与后端 Pydantic Schema 保持一致。
- 登录成功后 JWT 存于 `localStorage`（键 `hr-agent:access-token`），请求拦截器自动加
  `Authorization: Bearer <token>`。
- 刷新页面时，路由守卫调用 `GET /auth/me` 恢复用户信息；令牌失效则清理并跳转登录页。
- 任意接口返回 `401` 时，响应拦截器统一清理会话（登录接口本身的 401 除外，避免错误密码触发跳转）。
- 后端统一错误结构 `{ code, message, details, request_id, timestamp }` 被包装为 `ApiError`，
  页面直接展示 `message`，需要分支时使用 `code`。
- 开发环境用 Vite 代理；若改成直连后端，需要把前端地址加入后端 `CORS_ORIGINS`
  （默认已包含 `http://localhost:5173` 与 `http://127.0.0.1:5173`）。

### 已接入的接口

| 方法    | 路径                          | 用途                           |
| ------- | ----------------------------- | ------------------------------ |
| `POST`  | `/api/v1/auth/login`          | 登录并获取令牌                 |
| `GET`   | `/api/v1/auth/me`             | 恢复当前用户                   |
| `POST`  | `/api/v1/auth/logout`         | 退出登录（本地令牌一定会清除） |
| `GET`   | `/api/v1/jds`                 | JD 分页列表                    |
| `POST`  | `/api/v1/jds`                 | 保存 JD                        |
| `GET`   | `/api/v1/jds/{id}`            | JD 详情                        |
| `PATCH` | `/api/v1/jds/{id}`            | 编辑 JD                        |
| `POST`  | `/api/v1/jds/generate`        | AI 生成 JD（阻塞，不落库）     |
| `POST`  | `/api/v1/jds/generate/stream` | AI 流式生成 JD（SSE，不落库）  |

JD 管理页（`/jds`）支持列表 / 详情、状态筛选、新建、AI 流式生成与在线编辑。
AI 生成通过后端 Dify Chatflow type=1 完成：后端把 Dify SSE 归一化为
`start` / `delta` / `done` / `error`，前端用 `fetch` + `ReadableStream` 边收边渲染；
Markdown 正文由 `marked` 渲染并经 `DOMPurify` 清洗。

工作台中的统计指标与图表为演示数据，后续业务接口接入时替换 `DashboardView.vue` 中的数据源即可。

## 开发约定

- **Element Plus 按需加载**：模板中直接写 `<el-button>` 等组件，由 `unplugin-vue-components`
  自动引入；`ElMessage` / `ElMessageBox` 由 `unplugin-auto-import` 自动引入。生成的
  `src/auto-imports.d.ts`、`src/components.d.ts` 需要提交，删除后重新执行 `pnpm dev` 或
  `pnpm build` 会再生成。
- **ECharts 按需注册**：新增图表类型时，在 `src/plugins/echarts.ts` 的 `use([...])` 中补充，
  避免把整个 ECharts 打进产物。统一通过 `src/components/BaseChart.vue` 使用，它负责初始化、
  响应式更新、容器尺寸监听与销毁。
- **状态管理**：使用 Setup Store（`defineStore('name', () => {...})`），登录态集中在
  `src/stores/auth.ts`，组件不要直接读写 `localStorage` 令牌。
- **请求**：页面只调用 `src/api/*`，不要直接 `axios.get`；新增业务模块时按 domain 建文件。
- **路由**：需要登录的页面在 `meta.requiresAuth` 设为 `true`，标题写在 `meta.title`。
- **样式**：全局设计变量集中在 `src/styles/index.css`，页面样式使用 `<style scoped>`；
  Element Plus 主色通过 `--el-color-primary*` 变量覆盖。
- 新增组件/页面后，至少执行 `pnpm type-check`、`pnpm lint`、`pnpm build`。

## 部署

`pnpm build` 产出 `dist/`，将静态文件交给 Nginx 等服务器托管，并把未知路径回退到
`index.html`（history 路由要求）。若前后端不同源，把 `VITE_API_BASE_URL` 改成完整 API 地址，
同时配置后端 CORS；若同源，保持 `/api/v1` 并由网关把 `/api` 转发给 FastAPI 即可。
