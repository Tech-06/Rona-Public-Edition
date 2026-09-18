import asyncio
import json
import time
from typing import Any

STREAM_QUEUE_MAXSIZE = 256
STREAM_RING_SIZE = 200
STREAM_RUN_TTL_SECONDS = 120

Frame = tuple[int, str, dict[str, Any]]


def _offer(queue: asyncio.Queue, item: Frame) -> None:
    while True:
        try:
            queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return


class StreamRun:
    def __init__(self) -> None:
        self.ring: list[Frame] = []
        self.subscribers: list[asyncio.Queue] = []
        self.next_id = 1
        self.done = False
        self.finished_at: float | None = None
        self.task: asyncio.Task | None = None

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        frame: Frame = (self.next_id, event_type, data)
        self.next_id += 1
        self.ring.append(frame)
        if len(self.ring) > STREAM_RING_SIZE:
            self.ring.pop(0)
        for queue in self.subscribers:
            _offer(queue, frame)

    def finish(self) -> None:
        self.done = True
        self.finished_at = time.time()

    def subscribe(self, last_event_id: int) -> tuple[list[Frame], asyncio.Queue]:
        backlog = [frame for frame in self.ring if frame[0] > last_event_id]
        queue: asyncio.Queue = asyncio.Queue(maxsize=STREAM_QUEUE_MAXSIZE)
        self.subscribers.append(queue)
        return backlog, queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)


_runs: dict[str, StreamRun] = {}


def _sweep_expired() -> None:
    now = time.time()
    expired = [
        conversation_id
        for conversation_id, run in _runs.items()
        if run.done
        and run.finished_at is not None
        and now - run.finished_at > STREAM_RUN_TTL_SECONDS
    ]
    for conversation_id in expired:
        del _runs[conversation_id]


def get_or_create_run(conversation_id: str) -> tuple[StreamRun, bool]:
    _sweep_expired()
    existing = _runs.get(conversation_id)
    if existing is not None and not existing.done:
        return existing, False
    run = StreamRun()
    _runs[conversation_id] = run
    return run, True


def drop_run(conversation_id: str) -> None:
    """Discard a finished run's replay buffer immediately.

    Without this, a conversation deleted right after it finishes streaming
    stays replayable for up to STREAM_RUN_TTL_SECONDS: a reconnecting SSE
    subscriber would replay its buffered "done" frame, and the client's
    onDone handler would re-save the very conversation that was just
    deleted, resurrecting it.
    """
    _runs.pop(conversation_id, None)


def encode_frame(event_id: int, event_type: str, data: dict[str, Any]) -> str:
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event_type}\ndata: {body}\n\n"
