"""会话服务单元测试：CRUD、归属校验与问答落库辅助（不依赖数据库）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    BadRequestError,
    ConversationNotFoundError,
    KnowledgeBaseNotFoundError,
    MessageNotFoundError,
)
from app.db.models import Conversation, Message
from app.schemas.conversation import ConversationCreate, ConversationUpdate, MessageFeedback
from app.services import conversation_service, knowledge_base_service
from tests.fakes import make_user


class FakeScalarsResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def one(self) -> Any:
        assert len(self._rows) == 1
        return self._rows[0]


class FakeConversationSession:
    """覆盖会话服务用到的 AsyncSession 子集。"""

    def __init__(
        self,
        conversation: Conversation | None = None,
        messages: list[Message] | None = None,
    ) -> None:
        self.conversation = conversation
        self.messages = messages or []
        self.scalars_rows: list[Any] = []
        self.scalar_value: int | None = None
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commit_count = 0
        self.flush_count = 0

    async def get(self, model: type, pk: UUID) -> Any:
        if model is Conversation:
            if self.conversation is not None and self.conversation.id == pk:
                return self.conversation
            return None
        if model is Message:
            return next((m for m in self.messages if m.id == pk), None)
        return None

    async def scalar(self, statement: Any) -> Any:  # noqa: ARG002 - 不解析查询语句
        return self.scalar_value if self.scalar_value is not None else len(self.messages)

    async def scalars(self, statement: Any) -> FakeScalarsResult:  # noqa: ARG002
        return FakeScalarsResult(self.scalars_rows)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    async def refresh(self, obj: Any) -> None:
        pass


def make_conversation(user_id: UUID, **overrides: Any) -> Conversation:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "新会话",
        "kind": "knowledge",
        "status": "active",
        "knowledge_base_ids": [],
        "total_messages": 0,
        "user_id": user_id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return Conversation(**data)


def make_message(conversation_id: UUID, **overrides: Any) -> Message:
    data: dict[str, Any] = {
        "id": uuid4(),
        "conversation_id": conversation_id,
        "role": "user",
        "content": "年假有几天？",
        "created_at": datetime.now(UTC),
    }
    data.update(overrides)
    return Message(**data)


# ---------------------------------------------------------------------------
# 归属校验
# ---------------------------------------------------------------------------
async def test_get_conversation_returns_own_record() -> None:
    user = make_user()
    record = make_conversation(user.id)
    session = FakeConversationSession(conversation=record)

    result = await conversation_service.get_conversation(session, record.id, user=user)

    assert result is record


async def test_get_conversation_missing_raises_not_found() -> None:
    session = FakeConversationSession(conversation=None)

    with pytest.raises(ConversationNotFoundError):
        await conversation_service.get_conversation(session, uuid4(), user=make_user())


async def test_get_conversation_of_other_user_raises_not_found() -> None:
    record = make_conversation(uuid4())
    session = FakeConversationSession(conversation=record)

    with pytest.raises(ConversationNotFoundError):
        await conversation_service.get_conversation(session, record.id, user=make_user())


async def test_get_inactive_conversation_raises_not_found() -> None:
    user = make_user()
    record = make_conversation(user.id, is_active=False)
    session = FakeConversationSession(conversation=record)

    with pytest.raises(ConversationNotFoundError):
        await conversation_service.get_conversation(session, record.id, user=user)


# ---------------------------------------------------------------------------
# 创建 / 更新 / 删除
# ---------------------------------------------------------------------------
async def test_create_conversation_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    session = FakeConversationSession()

    async def fake_get_kb(db: Any, kb_id: UUID, *, user: Any) -> None:
        return None

    monkeypatch.setattr(knowledge_base_service, "get_knowledge_base", fake_get_kb)
    kb_id = uuid4()
    payload = ConversationCreate(knowledge_base_ids=[kb_id, kb_id])

    record = await conversation_service.create_conversation(session, payload, user=user)

    assert record.title == "新会话"
    assert record.user_id == user.id
    assert record.knowledge_base_ids == [str(kb_id)]  # 去重且存字符串
    assert record.total_messages == 0
    assert session.commit_count == 1


async def test_create_conversation_rejects_invisible_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_kb(db: Any, kb_id: UUID, *, user: Any) -> None:
        raise KnowledgeBaseNotFoundError()

    monkeypatch.setattr(knowledge_base_service, "get_knowledge_base", fake_get_kb)
    session = FakeConversationSession()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await conversation_service.create_conversation(
            session,
            ConversationCreate(knowledge_base_ids=[uuid4()]),
            user=make_user(),
        )
    assert session.added == []


async def test_update_conversation_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    record = make_conversation(user.id)
    session = FakeConversationSession(conversation=record)

    async def fake_get_kb(db: Any, kb_id: UUID, *, user: Any) -> None:
        return None

    monkeypatch.setattr(knowledge_base_service, "get_knowledge_base", fake_get_kb)
    kb_id = uuid4()
    payload = ConversationUpdate(
        title="员工手册咨询",
        status="archived",
        knowledge_base_ids=[kb_id],
    )

    updated = await conversation_service.update_conversation(session, record.id, payload, user=user)

    assert updated.title == "员工手册咨询"
    assert updated.status == "archived"
    assert updated.knowledge_base_ids == [str(kb_id)]
    assert updated.updated_by == user.id


async def test_update_conversation_null_title_rejected() -> None:
    user = make_user()
    record = make_conversation(user.id)
    session = FakeConversationSession(conversation=record)

    with pytest.raises(BadRequestError):
        await conversation_service.update_conversation(
            session,
            record.id,
            ConversationUpdate(title=None),
            user=user,
        )


async def test_delete_conversation_cascades_messages() -> None:
    user = make_user()
    record = make_conversation(user.id)
    record.messages = [make_message(record.id), make_message(record.id, role="assistant")]
    session = FakeConversationSession(conversation=record)
    session.scalars_rows = [record]

    await conversation_service.delete_conversation(session, record.id, user=user)

    assert session.deleted == [record]
    assert session.commit_count == 1


# ---------------------------------------------------------------------------
# 消息与反馈
# ---------------------------------------------------------------------------
async def test_get_message_rejects_other_conversation() -> None:
    user = make_user()
    record = make_conversation(user.id)
    other_message = make_message(uuid4())
    session = FakeConversationSession(conversation=record, messages=[other_message])

    with pytest.raises(MessageNotFoundError):
        await conversation_service.get_message(session, record.id, other_message.id, user=user)


async def test_update_message_feedback() -> None:
    user = make_user()
    record = make_conversation(user.id)
    message = make_message(record.id, role="assistant", content="回答")
    session = FakeConversationSession(conversation=record, messages=[message])

    updated = await conversation_service.update_message_feedback(
        session,
        record.id,
        message.id,
        MessageFeedback(rating=5, feedback="很有帮助"),
        user=user,
    )

    assert updated.rating == 5
    assert updated.feedback == "很有帮助"
    assert session.commit_count == 1


# ---------------------------------------------------------------------------
# 问答落库辅助
# ---------------------------------------------------------------------------
async def test_update_total_messages_recounts() -> None:
    user = make_user()
    record = make_conversation(user.id)
    session = FakeConversationSession(conversation=record)
    session.scalar_value = 4

    total = await conversation_service.update_total_messages(session, record.id)

    assert total == 4
    assert record.total_messages == 4
    assert session.flush_count == 1


def test_auto_title_only_when_default() -> None:
    user = make_user()
    record = make_conversation(user.id)
    long_question = "请问公司员工手册中关于带薪年假的天数是如何规定的，需要满足什么条件？"

    conversation_service.auto_title(record, long_question)
    assert record.title == long_question[:30]

    conversation_service.auto_title(record, "另一个问题")
    assert record.title == long_question[:30]  # 已有标题不再覆盖


def test_auto_title_keeps_default_for_blank_content() -> None:
    record = make_conversation(make_user().id)

    conversation_service.auto_title(record, "   ")

    assert record.title == "新会话"


async def test_validate_knowledge_base_ids_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[UUID] = []

    async def fake_get_kb(db: Any, kb_id: UUID, *, user: Any) -> None:
        seen.append(kb_id)

    monkeypatch.setattr(knowledge_base_service, "get_knowledge_base", fake_get_kb)
    first, second = uuid4(), uuid4()

    result = await conversation_service.validate_knowledge_base_ids(
        FakeConversationSession(),
        [first, second, first],
        user=make_user(),
    )

    assert result == [first, second]
    assert seen == [first, second]
