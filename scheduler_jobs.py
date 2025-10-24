import sys
import logging
import psutil
import time
from threading import Semaphore, Thread
from queue import Queue
from server import app, scheduler, Candidate, Job, db, run_daily_scrape, apply_one_job
from zoneinfo import ZoneInfo

# ----------------------------
# GLOBAL FATAL EXCEPTION HOOK
# ----------------------------
logger = logging.getLogger("fatal")

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

# ----------------------------
# CONFIGURATION
# ----------------------------
MAX_GLOBAL_CHROME = 1
CPU_THRESHOLD = 80.0
MEM_THRESHOLD = 80.0
GLOBAL_CHROME_SEMAPHORE = Semaphore(MAX_GLOBAL_CHROME)
RETRY_QUEUE = Queue()

# Per-candidate semaphore dict
candidate_semaphores = {}

def get_candidate_semaphore(candidate_id: int):
    if candidate_id not in candidate_semaphores:
        candidate_semaphores[candidate_id] = Semaphore(1)  # only 1 job per candidate
    return candidate_semaphores[candidate_id]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("adaptive_scheduler_retry")

# ----------------------------
# WRAPPED JOB FUNCTIONS WITH SEMAPHORES AND RETRY
# ----------------------------
def apply_one_job_safe(candidate_id):
    """Run apply_one_job with candidate + global semaphore and retry on failure."""
    candidate_sem = get_candidate_semaphore(candidate_id)

    acquired_candidate = candidate_sem.acquire(timeout=10)
    acquired_global = GLOBAL_CHROME_SEMAPHORE.acquire(timeout=10)

    if not acquired_candidate or not acquired_global:
        logger.warning(f"Candidate {candidate_id} or global limit reached. Skipping run.")
        if acquired_candidate:
            candidate_sem.release()
        if acquired_global:
            GLOBAL_CHROME_SEMAPHORE.release()
        return

    try:
        logger.info(f"🔹 Starting apply_one_job for candidate {candidate_id}")
        apply_one_job(candidate_id)
        logger.info(f"✅ Finished apply_one_job for candidate {candidate_id}")
    except Exception as e:
        logger.exception(f"❌ Failed apply_one_job for candidate {candidate_id}, retrying...")
        RETRY_QUEUE.put(("apply", candidate_id))
    finally:
        candidate_sem.release()
        GLOBAL_CHROME_SEMAPHORE.release()

def run_daily_scrape_safe(candidate_id):
    """Run daily scrape with candidate + global semaphore and retry on failure."""
    candidate_sem = get_candidate_semaphore(candidate_id)

    acquired_candidate = candidate_sem.acquire(timeout=10)
    acquired_global = GLOBAL_CHROME_SEMAPHORE.acquire(timeout=10)

    if not acquired_candidate or not acquired_global:
        logger.warning(f"Candidate {candidate_id} or global limit reached. Skipping daily scrape.")
        if acquired_candidate:
            candidate_sem.release()
        if acquired_global:
            GLOBAL_CHROME_SEMAPHORE.release()
        return

    try:
        logger.info(f"🔹 Starting daily scrape for candidate {candidate_id}")
        run_daily_scrape(candidate_id)
        logger.info(f"✅ Finished daily scrape for candidate {candidate_id}")
    except Exception as e:
        logger.exception(f"❌ Failed daily scrape for candidate {candidate_id}, retrying...")
        RETRY_QUEUE.put(("scrape", candidate_id))
    finally:
        candidate_sem.release()
        GLOBAL_CHROME_SEMAPHORE.release()

# ----------------------------
# RETRY WORKER
# ----------------------------
def retry_worker():
    while True:
        job_type, candidate_id = RETRY_QUEUE.get()
        try:
            if job_type == "apply":
                apply_one_job_safe(candidate_id)
            elif job_type == "scrape":
                run_daily_scrape_safe(candidate_id)
        finally:
            RETRY_QUEUE.task_done()
        time.sleep(1)

# ----------------------------
# RESOURCE ADAPTIVE CONTROLLER
# ----------------------------
def adjust_semaphore():
    while True:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent

        if cpu > CPU_THRESHOLD or mem > MEM_THRESHOLD:
            new_value = max(1, GLOBAL_CHROME_SEMAPHORE._value - 1)
            GLOBAL_CHROME_SEMAPHORE._value = new_value
            logger.info(f"High load (CPU: {cpu}%, RAM: {mem}%), throttling to {new_value} slots")
        else:
            new_value = min(MAX_GLOBAL_CHROME, GLOBAL_CHROME_SEMAPHORE._value + 1)
            GLOBAL_CHROME_SEMAPHORE._value = new_value
            logger.info(f"Resources free (CPU: {cpu}%, RAM: {mem}%), allowing {new_value} slots")

        time.sleep(5)

def idle_worker():
    """Continuously pick next queued job when server is idle."""
    logger.info("Idle worker thread started ✅")
    while True:
        try:
            with app.app_context():
                if GLOBAL_CHROME_SEMAPHORE._value > 0:
                    job = (
                        db.session.query(Job)
                        .filter(Job.status == "queued")
                        .order_by(Job.created_at.asc())
                        .first()
                    )
                    if job:
                        logger.info(
                            f"⚡ Idle worker picked job {job.id} for candidate {job.candidate_id}"
                        )
                        Thread(
                            target=apply_one_job_safe,
                            args=(job.candidate_id,),
                            daemon=True,
                        ).start()
                    else:
                        logger.debug("🛑 No queued jobs found")
            time.sleep(5)
        except Exception as e:
            logger.exception(f"Idle worker crashed: {e}")
            time.sleep(10)


# ----------------------------
# APSCHEDULER JOB SETUP
# ----------------------------
def schedule_candidate_jobs(candidate_id: int, tz_name="Asia/Kolkata"):
    tz = ZoneInfo(tz_name)

    scheduler.add_job(
        func=lambda cid=candidate_id: run_daily_scrape_safe(cid),
        trigger="cron",
        minute="0-59/15",
        hour="8-23,0",
        timezone=tz,
        id=f"daily-scrape-{candidate_id}",
        replace_existing=True
    )

    scheduler.add_job(
        func=lambda cid=candidate_id: apply_one_job_safe(cid),
        trigger="cron",
        minute="0-59/15",
        hour="8-23,0",
        timezone=tz,
        id=f"apply-interval-{candidate_id}",
        replace_existing=True
    )

# ----------------------------
# MAIN SCHEDULER INITIALIZATION
# ----------------------------
def run_adaptive_scheduler_with_retry():
    with app.app_context():
        scheduler.start()
        logger.info("APScheduler started")

        Thread(target=retry_worker, daemon=True).start()
        logger.info("Retry worker started")

        Thread(target=adjust_semaphore, daemon=True).start()
        logger.info("Resource adaptive controller started")

        Thread(target=idle_worker, daemon=True).start()
        logger.info("Idle worker started")

        active_candidates = (
            db.session.query(Candidate)
            .join(Job, Job.candidate_id == Candidate.id)
            .filter(Job.status.in_(["queued", "retry"]))
            .distinct()
            .all()
        )
        logger.info(f"Scheduling jobs for {len(active_candidates)} candidates")
        for cand in active_candidates:
            schedule_candidate_jobs(cand.id)

        while True:
            logger.info(f"Total scheduled jobs: {len(scheduler.get_jobs())} | "
                        f"Retry queue size: {RETRY_QUEUE.qsize()} | "
                        f"Available slots: {GLOBAL_CHROME_SEMAPHORE._value}")
            time.sleep(10)

# ----------------------------
# START
# ----------------------------
if __name__ == "__main__":
    run_adaptive_scheduler_with_retry()
