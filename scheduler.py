# scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from models import db, Candidate, Job
from universal_job_scraper import main as scrape_main

sched = BackgroundScheduler(timezone="UTC")  # run scheduler in UTC; schedule with aware datetimes

def daily_scrape(candidate_id):
    cand = Candidate.query.get(candidate_id)
    if not cand: return
    keywords = (cand.key_skills or "").split(",") or ["software","developer"]
    location = cand.preferred_location or "remote"
    scrape_main(keywords=keywords, location=location, remote=True, user_id=cand.id, db=db, Job=Job)

def apply_once(candidate_id):
    # pick next queued job for this candidate, run the right bot, update Job.status
    pass

def schedule_month(candidate_id, tz_name="America/New_York", start_utc=None):
    tz = ZoneInfo(tz_name)
    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    start_utc = start_utc or now_utc

    # 20 business days: schedule 07:30 scrape + paced applies 08:00–16:00 (candidate’s local time)
    days_scheduled = 0
    day_cursor = start_utc.astimezone(tz)
    while days_scheduled < 20:
        if day_cursor.weekday() < 5:  # Mon–Fri in candidate tz
            # 07:30 local → convert to UTC for the trigger
            scrape_local = day_cursor.replace(hour=7, minute=30, second=0, microsecond=0)
            sched.add_job(daily_scrape, trigger=DateTrigger(run_date=scrape_local.astimezone(ZoneInfo("UTC"))),
                          args=[candidate_id], id=f"scrape-{candidate_id}-{scrape_local.date()}", replace_existing=True)

            # 6–7 applies/hour across 8 hours with jitter
            for h in range(8):  # 08:00–16:00 local
                for slot in (0, 9, 18, 27, 36, 45, 54):  # ~every 9 minutes
                    local_time = scrape_local.replace(hour=8+h, minute=slot)
                    run_utc = local_time.astimezone(ZoneInfo("UTC"))
                    sched.add_job(apply_once, trigger=DateTrigger(run_date=run_utc),
                                  args=[candidate_id])
            days_scheduled += 1
        # next day in candidate tz
        day_cursor = (day_cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

def start_scheduler(app):
    # run inside app context; start only once
    with app.app_context():
        if not sched.running:
            sched.start()
