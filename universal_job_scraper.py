
import os
import logging
import json
import requests
from bs4 import BeautifulSoup
import datetime
from markdownify import markdownify as md
from openai import OpenAI
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from models import db, Job, User, Candidate
from urllib.parse import quote_plus

from flask import current_app
from datetime import datetime
from dotenv import load_dotenv

import undetected_chromedriver as uc
from selenium.webdriver.chrome.service import Service
# Load environment variables
load_dotenv()

# Initialize Perplexity API client
API_KEY = ""
BASE_URL = "https://api.perplexity.ai/chat/completions"

# Configure logging
logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# URLs for job boards
LINKEDIN_BASE_URL = "https://www.linkedin.com/jobs/search"
INDEED_BASE_URL = "https://www.indeed.com/jobs"

def fetch_page_requests(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching page {url}: {e}")
        return ""

import tempfile
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def fetch_page_selenium(url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # ✅ Create a truly unique temp user-data-dir for Chrome
    temp_dir = tempfile.mkdtemp(prefix="chrome-profile-")
    options.add_argument(f"--user-data-dir={temp_dir}")

    try:
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        # ✅ Wait until job listings are visible (adjust selector per site)
        WebDriverWait(driver, 40).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.base-card")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "section.two-pane-serp-page__results-list")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.scaffold-layout__list-container"))
            )
        )
        # Optionally scroll to trigger lazy load
        for i in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        if "captcha" in driver.page_source.lower():
            logger.info("LinkedIn blocked with CAPTCHA.")
            # handle CAPTCHA separately
            html = fetch_page_undetected(url)   # or pause for manual solving
            return html

        elif "login" in driver.current_url.lower():
            logger.info("LinkedIn redirected to login page.")
            # handle login separately
            html = fetch_page_requests(url)  # or login flow
            return html

        else:
            logger.info("Page loaded successfully.")
            html = driver.page_source
            return html

        html = driver.page_source
    finally:
        driver.quit()
        # ✅ Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

    return html

import random
import undetected_chromedriver as uc
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import random
import logging
from PIL import Image
import pytesseract
from io import BytesIO
import base64
from linkedin_bot_fixed import get_chrome_driver, get_chrome_driver_with_proxy


from linkedin_bot_fixed import get_chrome_driver  # import your shared driver helper

def fetch_page_undetected(url, proxy=None, li_at=None, use_ocr=False):
    """
    Fetch a web page using undetected-chromedriver with stealth features.
    Supports proxy, li_at session cookie (for LinkedIn), and OCR for CAPTCHAs.
    """
    logger.info("Enter fetch_page_undetected function.")

    # ✅ Choose driver based on domain
    if "indeed.com" in url:
        logger.info("Using Apify proxy for Indeed")
        driver = get_chrome_driver_with_proxy()
    else:
        logger.info("Using normal Chrome for LinkedIn or other sites")
        driver = get_chrome_driver()

    try:
        # Proxy support
        if proxy:
            logger.info(f"Using proxy: {proxy}")
            driver.execute_cdp_cmd(
                "Network.setExtraHTTPHeaders",
                {"headers": {"Proxy": proxy}}
            )

        # Inject LinkedIn session cookie
        if li_at:
            driver.get("https://www.linkedin.com")  # load domain first
            driver.add_cookie({
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })
            logger.info("li_at cookie injected successfully")

        driver.get(url)
        time.sleep(random.uniform(3, 6))  # random delay

        # Optional OCR for image CAPTCHAs
        if use_ocr:
            images = driver.find_elements("tag name", "img")
            for img in images:
                src = img.get_attribute("src")
                if "captcha" in src.lower() or "verify" in src.lower():
                    logger.info(f"CAPTCHA detected: {src}")
                    if src.startswith("data:image"):
                        header, encoded = src.split(",", 1)
                        img_bytes = base64.b64decode(encoded)
                        image = Image.open(BytesIO(img_bytes))
                        captcha_text = pytesseract.image_to_string(image)
                        logger.info(f"Detected CAPTCHA text: {captcha_text}")
                    else:
                        logger.warning("Remote CAPTCHA image not handled automatically")

        return driver.page_source

    finally:
        driver.quit()


def extract_linkedin_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    return md(str(soup))

def extract_indeed_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    return md(str(soup))

def build_prompt(markdown_content, keywords, location, source, skills=""):
    kw_str = ", ".join(keywords)
    skill_str = skills if skills else ""

    prompt = f"""
You are an expert web scraper. Extract up to 10 job postings from the content below that match any of these keywords: {kw_str}, 
skills: {skill_str}, and location containing '{location}'.

Return a JSON array of objects with fields: title, company, location, link, source.

Set the source field to '{source}' for all jobs.

Only return the JSON array, no other text.

CONTENT:

{markdown_content}
"""
    return prompt


def query_perplexity(prompt):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "sonar-pro",  # ✅ switched from pplx-70b-online to sonar-pro
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a scraping agent that returns scraped data "
                    "in raw JSON format with no other content."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0
    }

    try:
        res = requests.post(BASE_URL, headers=headers, json=data, timeout=30)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Perplexity API error: {e}")
        logger.error(f"Perplexity API error: {e}")
        return "[]"



def parse_jobs(json_str):
    logger.info(f"Enter parse_jobs function : {json_str}")
    try:
        if isinstance(json_str, str):
            return json.loads(json_str)  # Properly parse string to list of dicts
        return json_str  # Already parsed
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        logger.error(f"Error parsing JSON: {e}")
        return []
    
def scrape_linkedin(keywords, location, remote, user_id, skills="", title=""):
    logger.info("Enter scrape_linkedin function")
    combined_keywords = ""
    if title:
        combined_keywords += title + " "
    if keywords:
        combined_keywords += " ".join(keywords) if isinstance(keywords, list) else keywords
    if skills:
        combined_keywords += " " + skills.replace(",", " ")
    combined_keywords = combined_keywords.strip()

    query = combined_keywords.replace(" ", "+")
    # Normalize location
    if not location or location.lower() in ["us anywhere", "anywhere", "global"]:
        location_q = "United+States"
    else:
        location_q = location.replace(" ", "+")

    search_url = f"https://www.linkedin.com/jobs/search?keywords={query}&location={location_q}&f_TPR=r604800"
    print(f"Fetching LinkedIn jobs: {search_url}...")
    logger.info(f"Fetching LinkedIn jobs: {search_url}...")

    li_at = "AQEDATnvm9QDwvQ5AAABmGsHTWwAAAGZETyU700Axyb1hTQiM2vggIsaVZwIQpFUn8-Q9GvzwgiM5Qw9D7HsmR04xrbhvyfMcd5jlDjlLsFTxR4AREQdU44z2n_Oy7AemjG5REdiN6Ib7J4o2N7fXPkv"
    html = fetch_page_undetected(search_url, li_at=li_at)
    if not html:
        return []

    markdown_content = extract_linkedin_html(html)
    prompt = build_prompt(markdown_content, keywords, location, "LinkedIn", skills)

    json_response = query_perplexity(prompt)
    jobs = parse_jobs(json_response)

    for job in jobs:
        job['user_id'] = user_id
    return jobs

def scrape_indeed(keywords, location, remote, user_id, skills="", title=""):
    combined_keywords = ""
    if title:
        combined_keywords += title + " "
    if keywords:
        combined_keywords += " ".join(keywords) if isinstance(keywords, list) else keywords
    if skills:
        combined_keywords += " " + skills.replace(",", " ")
    combined_keywords = combined_keywords.strip()

    query = combined_keywords.replace(" ", "+")
    # Normalize location
    if not location or location.lower() in ["us anywhere", "anywhere", "global"]:
        location_q = "United+States"
    else:
        location_q = location.replace(" ", "+")

    search_url = f"{INDEED_BASE_URL}?q={query}&l={location_q}&fromage=7"
    print(f"Fetching Indeed jobs: {search_url}...")
    logger.info(f"Fetching Indeed jobs: {search_url}...")


    html = fetch_page_undetected(search_url,use_ocr=True)
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    results_container = (
    soup.find('div', {'id': 'mosaic-provider-jobcards'}) or
    soup.find('td', {'id': 'resultsCol'}) or
    soup
    )

    markdown_content = md(str(results_container))

    prompt = build_prompt(markdown_content, keywords, location, "Indeed", skills)
    json_response = query_perplexity(prompt)
    jobs = parse_jobs(json_response)

    for job in jobs:
        job['user_id'] = user_id
    return jobs

def save_jobs_to_db(jobs, db, Job):
    logger.info(f"Enter save_jobs_to_db function : {jobs}")
    if not jobs:
        print("No jobs to save.")
        return
    try:
        saved_count=0
        for job in jobs:
            existing_job = db.session.query(Job).filter_by(
                candidate_id=job['candidate_id'],  # Changed to filter by candidate_id
                link=job.get('link')
            ).first()
            if not existing_job:
                new_job = Job(
                    user_id=job.get('user_id', 0),
                    candidate_id=job.get('candidate_id'),  # ✅ this is critical
                    title=job.get('title') or 'Unknown Title',
                    company=job.get('company') or 'Unknown Company',
                    location=job.get('location') or 'Unknown Location',
                    link=job.get('link', ''),
                    source=job.get('source', ''),
                    created_at=datetime.now(),           # ✅ Required field
                    status='queued',    
                    comment='',
                    interview_status='',
                    final_verdict=''
                )
                db.session.add(new_job)
                saved_count += 1  # ✅ track saved jo
        db.session.commit()
        print(f"Saved {saved_count} new jobs to database")
        logger.info(f"Saved {saved_count} new jobs to database")
        print(f"Saved {len(jobs)} new jobs to database")
        logger.info(f"Saved {len(jobs)} new jobs to database")
    except Exception as e:
        db.session.rollback()
        print(f"Failed to save jobs to database: {str(e)}")
        logger.error(f"Failed to save jobs to database: {str(e)}")

def main(keywords=None, location='', remote=False, user_id=None, db=None, Job=None, max_jobs=10, skills="", title=""):
    if not user_id:
        print("Error: user_id is required")
        return []

    all_jobs = []

    logger.info(f"Enter main function in universal_job_scraper : {user_id}")
    scraping_functions = [
        lambda: scrape_linkedin(keywords, location, remote, user_id, skills, title),
        lambda: scrape_indeed(keywords, location, remote, user_id, skills, title),
    ]

    for scrape_func in scraping_functions:
        jobs = scrape_func()
        for job in jobs:
            if len(all_jobs) < max_jobs:
                job['candidate_id'] = user_id
                job['user_id'] = user_id
                all_jobs.append(job)
            else:
                break
        if len(all_jobs) >= max_jobs:
            break

    if not all_jobs:
        print("No jobs found across all platforms.")
        logger.info("No jobs found across all platforms.")
        return []

    print(f"Found {len(all_jobs)} jobs in total.")
    logger.info(f"Found {len(all_jobs)} jobs in total.")
    try:
        save_jobs_to_db(all_jobs, db, Job)
    except Exception as e:
        print("Failed to save jobs to database:", e)
        logger.error("Failed to save jobs to database:", e)

    return all_jobs

def fetch_page_web_unlocker_api(url, timeout=180):
    """
    Fetch a web page using Bright Data Web Unlocker API.
    Automatically bypasses CAPTCHAs and anti-bot protections.
    """
    logger.info(f"Fetching page via Bright Data Web Unlocker API: {url}")
    api_key = ""
    zone = "web_unlocker1"
    endpoint = "https://api.brightdata.com/request"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "zone": zone,
        "url": url,
        "format": "raw"  # returns raw HTML
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        if response.status_code == 200:
            logger.info("Page fetched successfully via Bright Data Web Unlocker API.")
            return response.text
        else:
            logger.warning(f"Failed to fetch page. Status code: {response.status_code}, Response: {response.text}")
            return None

    except requests.RequestException as e:
        logger.error(f"Error fetching page: {e}")
        return None


if __name__ == "__main__":
    print("This script should be called from server.py with appropriate parameters.")
