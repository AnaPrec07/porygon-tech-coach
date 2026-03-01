"""User domain entity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
    """
    Domain entity for authenticated users.

    In v1 (single-user), there is exactly one user. The model is
    designed to support multi-user without structural changes: all
    downstream entities carry user_id as a FK, enabling RLS in v2.
    """

    id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    display_name: str
    google_sub: str = Field(description="Google OAuth subject identifier")
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}
