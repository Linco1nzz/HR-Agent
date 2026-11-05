# Alembic 迁移目录

由 `uv run alembic init migrations` 生成，已按项目结构调整为从 `app.core.config` 读取数据库连接串。

常用命令（在 `backend/` 目录执行）：

```bash
uv run alembic revision --autogenerate -m "create xxx table"   # 根据模型生成迁移
uv run alembic upgrade head                                    # 应用迁移
uv run alembic downgrade -1                                    # 回退一步
uv run alembic current                                         # 当前版本
uv run alembic history                                         # 迁移历史
```

注意：

- 自动生成迁移前，模型必须已 `import` 到 `app/db/base.py` 的元数据中（可在 `app/db/models/`
  下集中定义，并在此处导入）。
- `versions/` 中的迁移脚本不要手动修改已应用到生产库的文件。
