"""Pins the scheduler-construction contract: `register_jobs` adds the
declared jobs against the constructed scheduler without ever starting it.

Starting an `AsyncIOScheduler` in a unit test would spin up a real
background thread; `register_jobs` is deliberately separate so this test
can assert what's wired up by inspecting `scheduler.get_jobs()`.
"""

from apscheduler.triggers.interval import IntervalTrigger

from src.jobs.hello_world import run_hello_world
from src.jobs.scheduler import make_scheduler, register_jobs


def test_register_jobs_adds_hello_world_with_interval_trigger():
    scheduler = make_scheduler()
    register_jobs(scheduler)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert "hello_world" in jobs

    hello = jobs["hello_world"]
    assert hello.func is run_hello_world
    assert isinstance(hello.trigger, IntervalTrigger)
    assert not scheduler.running


def test_register_jobs_respects_interval_env(monkeypatch):
    monkeypatch.setenv("JOBS_HELLO_WORLD_INTERVAL_MIN", "7")

    scheduler = make_scheduler()
    register_jobs(scheduler)

    hello = scheduler.get_job("hello_world")
    assert hello.trigger.interval.total_seconds() == 7 * 60
