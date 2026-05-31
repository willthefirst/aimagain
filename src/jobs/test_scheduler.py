"""Pins the scheduler-construction contract: `register_jobs` adds the
declared jobs against the constructed scheduler without ever starting it.

Starting an `AsyncIOScheduler` in a unit test would spin up a real
background thread; `register_jobs` is deliberately separate so this test
can assert what's wired up by inspecting `scheduler.get_jobs()`.
"""

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.jobs.hello_world import run_hello_world
from src.jobs.nightly_verification import run_nightly_verification
from src.jobs.scheduler import make_scheduler, register_jobs
from src.jobs.verify_pending_npis import run_verify_pending_npis


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


def test_register_jobs_adds_nightly_verification_with_cron_trigger():
    scheduler = make_scheduler()
    register_jobs(scheduler)

    nightly = scheduler.get_job("nightly_verification")
    assert nightly is not None
    assert nightly.func is run_nightly_verification
    assert isinstance(nightly.trigger, CronTrigger)
    # coalesce + max_instances=1 are what make the job safe across
    # missed windows and overlapping deploys.
    assert nightly.coalesce is True
    assert nightly.max_instances == 1


def test_register_jobs_respects_nightly_cron_env(monkeypatch):
    monkeypatch.setenv("JOBS_NIGHTLY_VERIFICATION_CRON", "*/5 * * * *")

    scheduler = make_scheduler()
    register_jobs(scheduler)

    nightly = scheduler.get_job("nightly_verification")
    # Cheapest assertion that proves the env var threaded through:
    # the parsed cron expression includes our minute spec.
    assert "*/5" in str(nightly.trigger)


def test_register_jobs_adds_verify_pending_npis_with_interval_trigger():
    scheduler = make_scheduler()
    register_jobs(scheduler)

    job = scheduler.get_job("verify_pending_npis")
    assert job is not None
    assert job.func is run_verify_pending_npis
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.coalesce is True
    assert job.max_instances == 1
    # Default cadence is 300s (prod baseline).
    assert job.trigger.interval.total_seconds() == 300


def test_register_jobs_respects_verify_pending_npis_interval_env(monkeypatch):
    monkeypatch.setenv("JOBS_VERIFY_PENDING_NPIS_INTERVAL_SEC", "60")

    scheduler = make_scheduler()
    register_jobs(scheduler)

    job = scheduler.get_job("verify_pending_npis")
    assert job.trigger.interval.total_seconds() == 60
