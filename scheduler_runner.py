import time
import logging
import psutil
from threading import Thread
from queue import Queue
from server import app, scheduler, Candidate, Job, db
from scheduler_jobs import (
    apply_one_job_safe,
    run_daily_scrape_safe,
    schedule_candidate_jobs,
    GLOBAL_CHROME_SEMAPHORE,
    RETRY_QUEUE,
    adjust_semaphore,
    retry_worker,
)

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_runner")

# ----------------------------
# Helper: Get active candidates (limit optional)
# ----------------------------
def get_active_candidates(limit=None):
    query = (
        db.session.query(Candidate)
        .join(Job, Job.candidate_id == Candidate.id)
        .filter(Job.status.in_(["queued", "retry"]))
        .distinct()
    )
    if limit:
        query = query.limit(limit)
    return query.all()

# ----------------------------
# Scheduler runner function
# ----------------------------
def run_scheduler(candidate_limit=None):
    with app.app_context():
        logger.info("Initializing scheduler from scheduler_runner.py")

        # Start APScheduler if not running
        if not scheduler.running:
            scheduler.start()
            logger.info("APScheduler started")

        # Start retry worker thread
        Thread(target=retry_worker, daemon=True).start()
        logger.info("Retry worker started")

        # Start resource-adaptive controller thread
        Thread(target=adjust_semaphore, daemon=True).start()
        logger.info("Resource adaptive controller started")

        # Fetch active candidates
        active_candidates = get_active_candidates(candidate_limit)
        if not active_candidates:
            logger.info("No candidates with queued/retry jobs found to schedule")
        else:
            logger.info(f"Found {len(active_candidates)} candidates with jobs to schedule")
            for cand in active_candidates:
                try:
                    schedule_candidate_jobs(cand.id)
                    logger.info(
                        f"Scheduled jobs for candidate {cand.id} "
                        f"({getattr(cand, 'name', 'N/A')})"
                    )
                except Exception as e:
                    logger.exception(f"Failed to schedule jobs for candidate {cand.id}: {e}")

        # Log all scheduled jobs
        jobs = scheduler.get_jobs()
        if not jobs:
            logger.info("⚠️ No jobs currently registered in scheduler")
        else:
            logger.info(f"🗂 {len(jobs)} jobs registered in scheduler:")
            for job in jobs:
                logger.info(f"   • {job.id} → next run: {job.next_run_time}")

        logger.info("✅ Scheduler initialized, entering main heartbeat loop")

        # Heartbeat loop
        while True:
            cpu_percent = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)

            logger.info(
                f"Scheduler heartbeat | CPU: {cpu_percent:.1f}% | "
                f"RAM Used: {rss_mb:.1f} MB (System: {mem.percent:.1f}%) | "
                f"Available Chrome slots: {GLOBAL_CHROME_SEMAPHORE._value} | "
                f"Retry queue size: {RETRY_QUEUE.qsize()} | "
                f"Scheduled jobs: {len(scheduler.get_jobs())}"
            )
            time.sleep(120)  # heartbeat every 2 minutes

# ----------------------------
# Crash protection loop
# ----------------------------
if __name__ == "__main__":
    while True:
        try:
            run_scheduler(candidate_limit=None)  # optionally set a limit
        except Exception as e:
            logger.exception(f"Scheduler crashed: {e}, restarting in 10s...")
            time.sleep(10)
