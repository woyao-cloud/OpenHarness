from __future__ import annotations

import time
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T | None = None
    timestamp: int = 0

    def model_post_init(self, __context: object) -> None:
        if self.timestamp == 0:
            self.timestamp = int(time.time() * 1000)

    @staticmethod
    def success(data: T | None = None) -> Result[T]:
        return Result(code=200, message="success", data=data)

    @staticmethod
    def error(message: str, code: int = 500) -> Result[None]:
        return Result(code=code, message=message)


class PageResult(BaseModel, Generic[T]):
    total: int = 0
    pages: int = 0
    current: int = 1
    size: int = 10
    records: list[T] = []