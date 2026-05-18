"""Scheduler construction and job registration.

`make_scheduler` and `register_jobs` are deliberately separate so tests
can introspect what's registered without starting the scheduler (calling
`.start()` would spin up a real background thread).
"""

import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.jobs.hello_world import run_hello_world
from src.jobs.nightly_verification import run_nightly_verification


def make_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    interval_min = int(os.getenv("JOBS_HELLO_WORLD_INTERVAL_MIN", "60"))
    scheduler.add_job(
        run_hello_world,
        trigger=IntervalTrigger(minutes=interval_min),
        id="hello_world",
        coalesce=True,
        max_instances=1,
    )

    # `coalesce=True` + `max_instances=1` together mean a missed window
    # (machine asleep, deploy in progress) collapses to a single run on
    # wake-up, and the job never double-fires if a previous run is still
    # in flight.
    nightly_cron = os.getenv("JOBS_NIGHTLY_VERIFICATION_CRON", "0 3 * * *")
    scheduler.add_job(
        run_nightly_verification,
        trigger=CronTrigger.from_crontab(nightly_cron),
        id="nightly_verification",
        coalesce=True,
        max_instances=1,
    )
