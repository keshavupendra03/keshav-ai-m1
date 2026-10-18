import asyncio
from keshav_AI import KeshavAIBot, EXTRACTION_FAILED_MESSAGE


class KeshavAIPool:
    """
    A small pool of independent KeshavAIBot workers, each owning its
    own browser page. Incoming questions are dropped onto one shared
    queue and picked up by whichever worker is free first.

    This shared-queue dispatch (rather than static round-robin
    assignment) minimizes wait time for any individual request: no
    worker ever sits idle while another has a backlog. With N
    workers, up to N requests are answered in parallel with no
    queueing at all; beyond that, requests wait in FIFO order and
    are picked up the instant any worker frees up.
    """

    # How many times to attempt a question before giving up. The
    # first attempt uses whatever identity its worker already has;
    # every retry forces that worker to recycle its browser identity
    # first, since a stale/throttled identity is the most common
    # reason an attempt fails (see KeshavAIBot.RECYCLE_EVERY_N_REQUESTS).
    MAX_ATTEMPTS = 2

    # Short pause between a failed attempt and the next retry, so a
    # transient hiccup has a moment to clear before trying again.
    RETRY_DELAY_SECONDS = 1.5

    def __init__(self, size: int = 4, headless: bool = True):
        self.size = size
        self.headless = headless

        self.workers = [
            KeshavAIBot(headless=headless, worker_id=i)
            for i in range(size)
        ]

        self.queue: asyncio.Queue = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []

    async def start(self):
        """Launch all worker browsers in parallel, then start
        each worker's dispatch loop."""

        print(
            f"Starting Keshav AI pool with {self.size} workers...",
            flush=True
        )

        # Parallel startup so cold-start time doesn't scale with
        # pool size (N browsers launching at once vs one by one).
        await asyncio.gather(*(worker.start() for worker in self.workers))

        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(worker))
            for worker in self.workers
        ]

        print(
            f"Keshav AI pool ready ({self.size} workers).",
            flush=True
        )

    async def _worker_loop(self, worker: KeshavAIBot):
        """Pull jobs off the shared queue for as long as the
        pool is running, one at a time, forever."""

        while True:

            question, force_recycle, future = await self.queue.get()

            try:

                if future.cancelled():
                    continue

                answer = await worker.ask(question, force_recycle=force_recycle)

                if not future.cancelled():
                    future.set_result(answer)

            except Exception as e:

                if not future.cancelled():
                    future.set_exception(e)

            finally:
                self.queue.task_done()

    async def _dispatch_once(
        self,
        question: str,
        force_recycle: bool,
        timeout: float
    ) -> str:
        """Queue a single attempt and wait for whichever worker
        picks it up to answer it."""

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        await self.queue.put((question, force_recycle, future))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            future.cancel()
            raise TimeoutError(
                f"No worker answered within {timeout} seconds."
            )

    async def ask(
        self,
        question: str,
        max_attempts: int = None,
        timeout: float = 120.0
    ) -> str:
        """
        Queue a question and return the answer, retrying on failure.

        The first attempt uses whatever worker is free next, with
        whatever identity it currently has. If that attempt raises
        (e.g. a transient Playwright error) or comes back as the
        "could not extract" sentinel (e.g. the "chat stopped
        unexpectedly" failure seen under load), every subsequent
        attempt forces a fresh browser identity before trying again -
        since a throttled/stale identity is the most common cause.

        Raises RuntimeError if every attempt fails, so the caller
        gets a clear, honest failure instead of a 200-OK response
        carrying a sentinel "no answer" string.
        """

        attempts = max_attempts or self.MAX_ATTEMPTS
        last_issue = "unknown"

        for attempt in range(1, attempts + 1):

            force_recycle = attempt > 1

            try:
                answer = await self._dispatch_once(
                    question, force_recycle, timeout
                )
            except Exception as e:
                last_issue = f"attempt {attempt} raised: {e}"
                answer = None

            if answer and answer != EXTRACTION_FAILED_MESSAGE:
                return answer

            if answer == EXTRACTION_FAILED_MESSAGE:
                last_issue = f"attempt {attempt} could not extract an answer"

            if attempt < attempts:
                await asyncio.sleep(self.RETRY_DELAY_SECONDS)

        raise RuntimeError(
            f"Keshav AI could not produce an answer after {attempts} "
            f"attempt(s) (last issue: {last_issue}). The upstream "
            "service may be temporarily rate-limited - please try "
            "again shortly."
        )

    async def close(self):
        """Stop all worker loops and close every browser."""

        print("Stopping Keshav AI pool...", flush=True)

        for task in self._worker_tasks:
            task.cancel()

        await asyncio.gather(*self._worker_tasks, return_exceptions=True)

        await asyncio.gather(*(worker.close() for worker in self.workers))

        print("Keshav AI pool stopped.", flush=True)
