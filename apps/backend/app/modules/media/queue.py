"""Постановка обработки файла в очередь.

Протокол, а не прямой вызов arq: HTTP-слой не должен знать, чем
исполняются фоновые задачи, а тесты подменяют очередь и запускают
обработку синхронно.
"""

from __future__ import annotations

from typing import Protocol

from app.workers.queue import enqueue

PROCESS_MEDIA_TASK = "process_media"


class MediaQueue(Protocol):
    async def enqueue_processing(self, media_id: int) -> None: ...


class ArqMediaQueue:
    async def enqueue_processing(self, media_id: int) -> None:
        await enqueue(PROCESS_MEDIA_TASK, media_id)


def get_media_queue() -> MediaQueue:
    return ArqMediaQueue()
