import time
import logging
import psutil
from server import app, start_bg_scheduler, schedule_day, Candidate, Job, db, scheduler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_runner")


def run_scheduler():
    with app.app_context():
        logger.info("Initializing scheduler from scheduler_runner.py")

        # Start scheduler
        start_bg_scheduler()
        logger.info("Background scheduler started")

        # Fetch and schedule candidates with queued/retry jobs
        active_candidates = (
            db.session.query(Candidate)
            .join(Job, Job.candidate_id == Candidate.id)
            .filter(Job.status.in_(["queued", "retry"]))
            .distinct()
            .all()
        )

        if not active_candidates:
            logger.info("No candidates with queued/retry jobs found to schedule")
        else:
            logger.info(f"Found {len(active_candidates)} candidates with jobs to schedule")
            for idx, cand in enumerate(active_candidates):
                try:
                    schedule_day(cand.id, stagger_index=idx)  # pass stagger_index here
                    logger.info(
                        f"Scheduled jobs for candidate {cand.id} "
                        f"({getattr(cand, 'name', 'N/A')})"
                    )
                except Exception as e:
                    logger.exception(f"Failed to schedule jobs for candidate {cand.id}: {e}")


        # ✅ List all scheduled jobs with next run times
        jobs = scheduler.get_jobs()
        if not jobs:
            logger.info("⚠️ No jobs currently registered in scheduler")
        else:
            logger.info(f"🗂 {len(jobs)} jobs registered in scheduler:")
            for job in jobs:
                logger.info(f"   • {job.id} → next run: {job.next_run_time}")

        logger.info("✅ Scheduler initialized, entering main loop")

        # Heartbeat loop
        while True:
            # Get CPU & memory usage
            cpu_percent = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)

            logger.info(
                f"Scheduler heartbeat - still running | "
                f"CPU: {cpu_percent:.1f}% | "
                f"RAM Used: {rss_mb:.1f} MB (System: {mem.percent:.1f}%)"
            )
            time.sleep(300)  # heartbeat every 5 minutes


# Restart loop with crash protection
while True:
    try:
        run_scheduler()
    except Exception as e:
        logger.exception(f"Scheduler crashed: {e}, restarting in 10s...")
        time.sleep(10)
