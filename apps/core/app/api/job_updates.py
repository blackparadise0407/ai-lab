from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class JobUpdateEvent:
    job_id: int
    event: str


@dataclass(eq=False)
class JobSubscription:
    job_id: int
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[JobUpdateEvent]


@dataclass(eq=False)
class GlobalJobSubscription:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[JobUpdateEvent]


class JobUpdateBroker:
    def __init__(self) -> None:
        self._subscriptions: dict[int, set[JobSubscription]] = {}
        self._global_subscriptions: set[GlobalJobSubscription] = set()
        self._lock = threading.RLock()

    async def subscribe(self, job_id: int) -> JobSubscription:
        subscription = JobSubscription(
            job_id=job_id,
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=10),
        )
        with self._lock:
            self._subscriptions.setdefault(job_id, set()).add(subscription)
        return subscription

    async def subscribe_all(self) -> GlobalJobSubscription:
        subscription = GlobalJobSubscription(
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=50),
        )
        with self._lock:
            self._global_subscriptions.add(subscription)
        return subscription

    async def unsubscribe(self, subscription: JobSubscription) -> None:
        with self._lock:
            subscriptions = self._subscriptions.get(subscription.job_id)
            if not subscriptions:
                return
            subscriptions.discard(subscription)
            if not subscriptions:
                self._subscriptions.pop(subscription.job_id, None)

    async def unsubscribe_all(self, subscription: GlobalJobSubscription) -> None:
        with self._lock:
            self._global_subscriptions.discard(subscription)

    def notify(self, job_id: int, event: str = "job_updated") -> None:
        update = JobUpdateEvent(job_id=job_id, event=event)
        with self._lock:
            subscriptions = list(self._subscriptions.get(job_id, set()))
            global_subscriptions = list(self._global_subscriptions)
        for subscription in subscriptions:
            subscription.loop.call_soon_threadsafe(
                self._enqueue_latest_event, subscription, update
            )
        for subscription in global_subscriptions:
            subscription.loop.call_soon_threadsafe(
                self._enqueue_latest_event, subscription, update
            )

    def _enqueue_latest_event(
        self,
        subscription: JobSubscription | GlobalJobSubscription,
        event: JobUpdateEvent,
    ) -> None:
        if subscription.queue.full():
            try:
                subscription.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        subscription.queue.put_nowait(event)


job_update_broker = JobUpdateBroker()
