"""知识库文档业务逻辑：上传、解析、切块、向量化入库与删除。

处理链路（上传后同步执行）：

1. 文件落盘保存（``uploads/knowledge_bases/<user_id>/``）；
2. 解析：复制到临时文件后提取纯文本（见 ``document_parser_service``）；
3. 切块：LLM 语义分割点 + LangChain 递归切分 + 长度约束（见
   ``document_chunking_service``）；
4. 向量化入库：由 ``embedding_service`` 生成向量，交给 ``vector_store_service``
   写入 LangChain PGVector 的 ``langchain_pg_embedding`` 表。

处理失败不会回滚已保存的文件与文档记录，而是把 ``processing_status`` 置为
``failed`` 并写入 ``processing_error``，便于前端提示与重新处理。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import aiofiles
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, settings
from app.core.exceptions import (
    AppException,
    DocumentDuplicateError,
    DocumentNotFoundError,
    ForbiddenError,
)
from app.core.logging import get_logger
from app.db.models import Document, KnowledgeBase, User
from app.schemas.document import (
    DocumentChunkItem,
    DocumentContentResponse,
    DocumentListItem,
    DocumentRead,
    ProcessingStatus,
)
from app.services import (
    document_chunking_service,
    document_parser_service,
    knowledge_base_service,
    vector_store_service,
)

logger = get_logger(__name__)

_MANAGE_DENIED_MESSAGE = "无权操作该文档"
_VIEW_DENIED_MESSAGE = "无权访问该文档"


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
async def list_documents(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    user: User,
    knowledge_base_id: UUID | None = None,
    unassigned: bool = False,
    keyword: str | None = None,
    processing_status: ProcessingStatus | None = None,
) -> tuple[list[Document], int]:
    """分页查询可见文档，按创建时间倒序。"""
    filters: list[ColumnElement[bool]] = [Document.is_active.is_(True)]
    filters.extend(_visibility_filters(user))

    if unassigned:
        filters.append(Document.knowledge_base_id.is_(None))
    elif knowledge_base_id is not None:
        filters.append(Document.knowledge_base_id == knowledge_base_id)

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                Document.original_filename.ilike(pattern),
                Document.extracted_content.ilike(pattern),
            )
        )
    if processing_status is not None:
        filters.append(Document.processing_status == processing_status.value)

    total = await db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
    stmt = (
        select(Document)
        .where(*filters)
        .order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_document(db: AsyncSession, document_id: UUID, *, user: User) -> Document:
    """按 ID 获取可见文档。"""
    record = await db.get(Document, document_id)
    if record is None or not record.is_active:
        raise DocumentNotFoundError(details={"document_id": str(document_id)})
    await _ensure_can_view(db, record, user)
    return record


async def list_chunks(
    db: AsyncSession, document_id: UUID, *, user: User
) -> list[DocumentChunkItem]:
    """返回文档的全部分块预览，按序号升序（来自 PGVector）。"""
    await get_document(db, document_id, user=user)
    return await vector_store_service.list_document_chunks(document_id)


async def knowledge_base_name(db: AsyncSession, record: Document) -> str | None:
    """查询文档所属知识库名称（未关联或已删除时为 ``None``）。"""
    if record.knowledge_base_id is None:
        return None
    names = await knowledge_base_service.names_by_id(db, [record.knowledge_base_id])
    return names.get(record.knowledge_base_id)


# ---------------------------------------------------------------------------
# 上传与处理
# ---------------------------------------------------------------------------
async def upload_document(
    db: AsyncSession,
    *,
    knowledge_base_id: UUID,
    filename: str,
    content: bytes,
    mime_type: str | None,
    user: User,
) -> Document:
    """保存上传文件、落库并同步完成解析 / 切块 / 向量化。"""
    knowledge_base = await knowledge_base_service.get_knowledge_base(
        db,
        knowledge_base_id,
        user=user,
    )
    suffix = document_parser_service.validate_document(filename, len(content))
    file_hash = hashlib.sha256(content).hexdigest()
    await _ensure_not_duplicate(db, knowledge_base.id, file_hash)

    document_id = uuid4()
    stored_path = await _save_document_file(content, suffix, document_id, user.id)
    record = Document(
        id=document_id,
        filename=stored_path.name,
        original_filename=Path(filename).name[:255],
        file_path=str(stored_path),
        file_size=len(content),
        file_hash=file_hash,
        mime_type=mime_type or document_parser_service.guess_mime_type(filename),
        processing_status=ProcessingStatus.UPLOADED.value,
        chunk_count=0,
        meta_data={"file_suffix": suffix, "embedding_model": settings.embedding_model},
        user_id=user.id,
        knowledge_base_id=knowledge_base.id,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(record)
    knowledge_base.document_count = (knowledge_base.document_count or 0) + 1

    try:
        await db.commit()
        await db.refresh(record)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise

    logger.info(
        "document_uploaded",
        document_id=str(record.id),
        knowledge_base_id=str(knowledge_base.id),
        user_id=str(user.id),
        file_size=record.file_size,
    )
    return await process_document(db, record)


async def process_document(db: AsyncSession, document: Document) -> Document:
    """从已保存的文件解析、切块、向量化并写入分块；失败时记录状态而不是抛出。

    解析前会把文件复制到临时文件再提取正文（见 ``document_parser_service``）。
    """
    await _reset_chunks(db, document)

    try:
        raw = await _read_file(document.file_path)
        text = await document_parser_service.extract_document_text(
            raw,
            document.original_filename,
        )
        chunks = await document_chunking_service.split_into_chunks(text)
        chunk_count = await vector_store_service.add_document_chunks(
            document_id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            user_id=document.user_id,
            original_filename=document.original_filename,
            chunks=chunks,
        )

        document.extracted_content = text
        document.chunk_count = chunk_count
        document.processing_status = ProcessingStatus.PROCESSED.value
        document.processing_error = None
        document.processed_at = datetime.now(UTC)
        document.meta_data = {
            **(document.meta_data or {}),
            "embedding_model": settings.embedding_model,
            "chunk_size": settings.knowledge_base_chunk_size,
            "chunk_overlap": settings.knowledge_base_chunk_overlap,
        }

        await db.commit()
        await db.refresh(document)
        logger.info(
            "document_processed",
            document_id=str(document.id),
            knowledge_base_id=(
                str(document.knowledge_base_id) if document.knowledge_base_id else None
            ),
            chunks=document.chunk_count,
            content_chars=len(text),
        )
    except Exception as exc:  # noqa: BLE001 - 处理失败要落库为 failed，而不是让上传失败
        await db.rollback()
        await db.refresh(document)
        document.processing_status = ProcessingStatus.FAILED.value
        document.processing_error = _describe_error(exc)[:2000]
        document.chunk_count = 0
        await db.commit()
        await db.refresh(document)
        logger.warning(
            "document_processing_failed",
            document_id=str(document.id),
            user_id=str(document.user_id),
            error=document.processing_error,
        )

    return document


async def reprocess_document(db: AsyncSession, document_id: UUID, *, user: User) -> Document:
    """重新解析 / 切块 / 向量化（上传者或管理员）。"""
    record = await _get_manageable_document(db, document_id, user)
    return await process_document(db, record)


async def delete_document(db: AsyncSession, document_id: UUID, *, user: User) -> None:
    """删除文档：清理 PGVector 分块向量、文档记录与磁盘文件（上传者或管理员）。"""
    record = await _get_manageable_document(db, document_id, user)
    knowledge_base_id = record.knowledge_base_id
    file_path = record.file_path

    # 先清理向量；失败则保留文档记录，避免丢失数据
    await vector_store_service.delete_document_chunks(record.id)
    if knowledge_base_id is not None:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        if knowledge_base is not None:
            knowledge_base.document_count = max(0, (knowledge_base.document_count or 0) - 1)
            knowledge_base.updated_by = user.id

    await db.delete(record)
    await db.commit()
    _remove_file(file_path)
    logger.info(
        "document_deleted",
        document_id=str(document_id),
        knowledge_base_id=str(knowledge_base_id) if knowledge_base_id else None,
        user_id=str(user.id),
    )


# ---------------------------------------------------------------------------
# 模型转换
# ---------------------------------------------------------------------------
def to_list_item(record: Document, knowledge_base_name: str | None = None) -> DocumentListItem:
    """ORM 记录转列表项，并补上知识库名称。"""
    return DocumentListItem.model_validate(record).model_copy(
        update={"knowledge_base_name": knowledge_base_name}
    )


def to_read(record: Document, knowledge_base_name: str | None = None) -> DocumentRead:
    """ORM 记录转详情。"""
    return DocumentRead.model_validate(record).model_copy(
        update={"knowledge_base_name": knowledge_base_name}
    )


def to_content(record: Document) -> DocumentContentResponse:
    """组装原始文本预览。"""
    content = record.extracted_content or ""
    return DocumentContentResponse(
        document_id=record.id,
        original_filename=record.original_filename,
        mime_type=record.mime_type,
        content=content,
        char_count=len(content),
        chunk_count=record.chunk_count,
        processing_status=ProcessingStatus(record.processing_status),
    )


# ---------------------------------------------------------------------------
# 权限与内部辅助
# ---------------------------------------------------------------------------
def _visibility_filters(user: User) -> list[ColumnElement[bool]]:
    """管理员可见全部；其他人可见公开 / 自己创建知识库下的文档，以及自己上传的未关联文档。"""
    if knowledge_base_service.is_admin(user):
        return []
    visible_knowledge_bases = select(KnowledgeBase.id).where(
        KnowledgeBase.is_active.is_(True),
        or_(
            KnowledgeBase.is_public.is_(True),
            KnowledgeBase.created_by == user.id,
        ),
    )
    return [
        or_(
            Document.knowledge_base_id.in_(visible_knowledge_bases),
            and_(Document.knowledge_base_id.is_(None), Document.user_id == user.id),
        )
    ]


async def _ensure_can_view(db: AsyncSession, record: Document, user: User) -> None:
    if knowledge_base_service.is_admin(user) or record.user_id == user.id:
        return
    if record.knowledge_base_id is None:
        raise ForbiddenError(_VIEW_DENIED_MESSAGE)
    knowledge_base = await db.get(KnowledgeBase, record.knowledge_base_id)
    if knowledge_base is not None and knowledge_base.is_active and knowledge_base.is_public:
        return
    raise ForbiddenError(_VIEW_DENIED_MESSAGE)


async def _get_manageable_document(
    db: AsyncSession,
    document_id: UUID,
    user: User,
) -> Document:
    """取文档并校验管理权限：上传者或管理员。"""
    record = await db.get(Document, document_id)
    if record is None or not record.is_active:
        raise DocumentNotFoundError(details={"document_id": str(document_id)})
    if knowledge_base_service.is_admin(user) or record.user_id == user.id:
        return record
    raise ForbiddenError(_MANAGE_DENIED_MESSAGE)


async def _ensure_not_duplicate(
    db: AsyncSession,
    knowledge_base_id: UUID,
    file_hash: str,
) -> None:
    stmt = (
        select(Document.id)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.file_hash == file_hash,
            Document.is_active.is_(True),
        )
        .limit(1)
    )
    if await db.scalar(stmt) is not None:
        raise DocumentDuplicateError(details={"file_hash": file_hash})


async def _reset_chunks(db: AsyncSession, document: Document) -> None:
    """进入处理状态前清空旧分块向量，保证失败时不会残留过期向量。"""
    document.processing_status = ProcessingStatus.PROCESSING.value
    document.processing_error = None
    document.chunk_count = 0
    await vector_store_service.delete_document_chunks(document.id)
    await db.commit()
    await db.refresh(document)


def _upload_directory() -> Path:
    root = Path(settings.knowledge_base_upload_dir)
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return root


async def _save_document_file(
    content: bytes,
    suffix: str,
    document_id: UUID,
    user_id: UUID,
) -> Path:
    directory = _upload_directory() / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document_id.hex}{suffix}"
    async with aiofiles.open(path, "wb") as handle:
        await handle.write(content)
    return path


async def _read_file(path: str) -> bytes:
    async with aiofiles.open(path, "rb") as handle:
        return await handle.read()


def _remove_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        # 文件清理失败不影响数据库删除，只记录日志供人工处理
        logger.warning("document_file_delete_failed", path=path, error=str(exc))


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, AppException):
        return exc.message
    return f"{type(exc).__name__}: {exc}"
