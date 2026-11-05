-- =============================================================================
-- PostgreSQL 初始化脚本
-- 仅在数据卷为空、首次启动容器时由 docker-entrypoint-initdb.d 自动执行。
-- 之后若要新增扩展，请手动执行：CREATE EXTENSION IF NOT EXISTS <name>;
-- =============================================================================

-- 向量类型、距离运算符与 HNSW / IVFFlat 索引（pgvector）
CREATE EXTENSION IF NOT EXISTS vector;

-- 模糊匹配与相似度查询（简历、职位描述文本检索）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- gen_random_uuid()、digest() 等加密/哈希函数
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 输出已安装扩展，便于在容器日志中确认初始化结果
SELECT extname, extversion FROM pg_extension ORDER BY extname;
