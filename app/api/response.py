"""Shared API response envelope."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: T | None = None


def ok(message: str, data: Any = None) -> dict[str, Any]:
    return {"success": True, "message": message, "data": data}


def fail(message: str) -> dict[str, Any]:
    return {"success": False, "message": message, "data": None}


class PageMeta(BaseModel):
    page: int = Field(ge=1)
    size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total: int