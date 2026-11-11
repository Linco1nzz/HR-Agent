"""ORM 模型包。

在此定义模型，并确保 `app.db.models` 被 Alembic 的 `migrations/env.py` 导入，
这样 `alembic revision --autogenerate` 才能发现新表。

所有模型继承 `app.db.base.BaseModel`，自动获得主键、创建/更新时间、
创建/更新人、是否启用等公共字段；未显式声明 `__tablename__` 时按类名自动生成表名::

    from sqlalchemy import String
    from sqlalchemy.orm import Mapped, mapped_column

    from app.db.base import BaseModel


    class Employee(BaseModel):  # 自动使用表名 employee
        name: Mapped[str] = mapped_column(String(64))

已定义的模型统一在此导入，供 Alembic 及业务代码使用。
"""

from app.db.models.job_description import JobDescription
from app.db.models.resume_evaluation import ResumeEvaluation
from app.db.models.scoring_criteria import ScoringCriteria
from app.db.models.user import Role, User, UserRoleAssociation

__all__ = [
    "JobDescription",
    "ResumeEvaluation",
    "Role",
    "ScoringCriteria",
    "User",
    "UserRoleAssociation",
]
