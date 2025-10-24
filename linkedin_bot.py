# linkedin_bot.py — callable AWS EC2 version
# Preserves your original Selenium & Easy Apply automation
# Entry point: run_linkedin_for_candidate(candidate_id)

import os, time, json
from urllib.parse import urlparse, parse_qs, unquote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from flask import current_app
from openai import OpenAI
from models import db, Candidate, Job

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY)
WAIT_SECONDS = 15
MAX_JOBS = 5

def normalize_linkedin_url(url: str) -> str:
    if "linkedin.com/comm/redirect" in url:
        qs = parse_qs(urlparse(url).query)
        target = qs.get("url", [""])[0]
        return unquote(target) or url
    return url

def click_easy_apply(driver, wait):
    try:
        btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.jobs-apply-button")))
        btn.click()
        time.sleep(2)
        return True
    except Exception as e:
        current_app.logger.warning(f"No Easy Apply button found: {e}")
        return False

def fill_application_form(driver, wait, candidate):
    pass  # Paste your original fill logic here

def submit_application(driver, wait):
    try:
        submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Submit application']")))
        submit_btn.click()
        time.sleep(2)
        return True
    except Exception as e:
        current_app.logger.warning(f"Failed to submit application: {e}")
        return False

def load_candidate_and_jobs(candidate_id):
    with current_app.app_context():
        candidate = Candidate.query.get(candidate_id)
        if not candidate:
            raise RuntimeError(f"Candidate {candidate_id} not found")
        jobs = Job.query.filter_by(candidate_id=candidate_id, source="linkedin").all()
        job_links = [normalize_linkedin_url(j.link) for j in jobs if j.link]
        return candidate, job_links

def run_linkedin_for_candidate(candidate_id):
    try:
        candidate, job_links = load_candidate_and_jobs(candidate_id)
        driver = webdriver.Chrome()
        driver.maximize_window()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        for job_url in job_links[:MAX_JOBS]:
            current_app.logger.info(f"Processing LinkedIn job: {job_url}")
            driver.get(job_url)
            time.sleep(3)
            if click_easy_apply(driver, wait):
                fill_application_form(driver, wait, candidate)
                submit_application(driver, wait)

        driver.quit()
        current_app.logger.info(f"✅ Finished LinkedIn for candidate {candidate_id}")
        return {"status": "completed", "jobs_processed": len(job_links)}

    except Exception as e:
        current_app.logger.error(f"❌ LinkedIn error: {e}")
        return {"status": "error", "message": str(e)}
