# indeed.py — callable AWS EC2 version
# Preserves your original Selenium & ATS automation logic
# Entry point: run_indeed_for_candidate(candidate_id)

import os, re, time, json, urllib, requests
import logging
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from urllib.parse import urlparse
from flask import current_app
from openai import OpenAI
from models import db, User, Candidate, Job
import argparse

# ====== CONFIG ======
MAX_JOBS = 1
WAIT_SECONDS = 15
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY)

# Chrome driver options
options = Options()
options.add_argument("--start-maximized")
options.add_argument("user-agent=Mozilla/5.0")

# Configure logging
logger = logging.getLogger(__name__)

def slugify_company(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def candidate_ats_urls(company_name: str):
    slug = slugify_company(company_name)
    return [
        f"https://recruiterflow.com/{slug}/jobs",
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://{slug}.bamboohr.com/careers",
        f"https://careers.smartrecruiters.com/{company_name}",
        f"https://jobs.ashbyhq.com/{company_name}",
        f"https://{slug}.myworkdayjobs.com/en-US/External",
        f"https://{slug}.myworkdayjobs.com/en-US/careers",
        f"https://careers-{slug}.icims.com",
        f"https://jobs.jobvite.com/{slug}",
    ]

def looks_like_ats(html: str, url: str) -> bool:
    h, u = html.lower(), url.lower()
    return any(x in u for x in [
        "recruiterflow.com","greenhouse.io","lever.co","myworkdayjobs.com",
        "bamboohr.com","smartrecruiters.com","ashbyhq.com","icims.com","jobvite.com"
    ]) or any(x in h for x in [
        "greenhouse","lever.co","workday","recruiterflow","smartrecruiters",
        "ashby","bamboohr","icims","jobvite"
    ])

def http_ok(url: str):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"}, allow_redirects=True)
        return (200 <= r.status_code < 300, r.text)
    except Exception:
        return (False, "")

def ddg_first_career_result(company_name: str):
    q = f"{company_name} careers"
    url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(q)
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            if href and any(k in href.lower() for k in
                ["careers","jobs","workday","greenhouse","lever","recruiterflow",
                 "smartrecruiters","icims","jobvite","ashbyhq","bamboohr"]):
                return href
    except Exception:
        pass
    return None

def find_employer_career_url(company_name: str) -> str | None:
    for cand in candidate_ats_urls(company_name):
        ok, html = http_ok(cand)
        if ok and looks_like_ats(html, cand):
            return cand
    hit = ddg_first_career_result(company_name)
    if hit:
        ok, html = http_ok(hit)
        if ok:
            return hit
    return None

def check_for_captcha():
    html = driver.page_source.lower()
    return any(x in html for x in ["captcha","h-captcha","cf-challenge","unusual traffic"])

def scroll_until_jobs_loaded():
    prev = 0
    while True:
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
        time.sleep(1.8)
        cards = driver.find_elements(By.XPATH, "//a[contains(@class,'jcs-JobTitle')]")
        if len(cards) > prev:
            prev = len(cards)
        else:
            break
    print(f"✅ Total job cards loaded: {prev}")

def load_profile_and_jobs(candidate_id):
    with current_app.app_context():
        cand = Candidate.query.get(candidate_id)
        if not cand:
            raise RuntimeError(f"Candidate {candidate_id} not found")
        recruiter = User.query.get(cand.recruiter_id)

        user_details = {
            "first_name": getattr(recruiter, "first_name", "") or "",
            "last_name": getattr(recruiter, "last_name", "") or "",
            "email": getattr(recruiter, "email", "") or "",
            "phone": getattr(recruiter, "phone", "") or "",
            "resume_path": getattr(cand, "resume_path", "") or "",
            "work_authorization": getattr(cand, "work_authorization", "") or "",
            "preferred_location": getattr(cand, "preferred_location", "") or "",
            "key_skills": getattr(cand, "key_skills", "") or "",
            "employment": getattr(cand, "employment", "") or "",
            "education": getattr(cand, "education", "") or "",
            "certifications": getattr(cand, "certifications", "") or "",
            "projects": getattr(cand, "projects", "") or "",
        }

        jobs = Job.query.filter_by(candidate_id=candidate_id, source="indeed").all()
        job_urls = [j.link for j in jobs if j.link and j.link.startswith("http")]
        return user_details, job_urls

from linkedin_bot_fixed import get_chrome_driver_with_proxy

def run_indeed_for_candidate(candidate_id, flask_app):
    logger.info(f"Enter run_indeed_for_candidate function candidate_id : {candidate_id}")
    with flask_app.app_context():
        driver = None  # Initialize driver first
        try:
            user_details, job_urls = load_profile_and_jobs(candidate_id)

            # 🔑 Use shared driver helper (auto-detect version + UA rotation)
            driver = get_chrome_driver_with_proxy()
            wait = WebDriverWait(driver, WAIT_SECONDS)

            for url in job_urls[:MAX_JOBS]:
                process_job_url(url, user_details)

            logger.info(f"Finished Indeed for candidate {candidate_id}")
            return {"status": "completed", "jobs_processed": len(job_urls)}

        except Exception as e:
            logger.exception(f"❌ Indeed error: {e}")
            return {"status": "error", "message": str(e)}

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.warning(f"Failed to quit Chrome driver cleanly: {e}")




def is_indeed(url: str) -> bool:
    try:
        return "indeed." in urlparse(url).netloc
    except:
        return False

def process_job_url(url, user_details):
    if is_indeed(url):
        # open Indeed page to resolve employer careers site, then fill via LLM
        process_indeed_job(url, user_details)
    else:
        # go straight to the link and run the LLM filling loop
        print(f"\n🔗 Processing ATS/careers link: {url}")
        logger.info(f"\n🔗 Processing ATS/careers link: {url}")
        driver.get(url); time.sleep(3)
        for attempt in range(3):
            fields = scrape_form_fields()
            mapping = ask_llm_to_match_fields(fields, user_details) if fields else {}
            filled = fill_fields_from_mapping(mapping, user_details) if mapping else set()
            fill_remaining_fields_smart(user_details, filled)
            if try_click_submit():
                print("✅ Submission likely succeeded.")
                logger.info("✅ Submission likely succeeded.")
                break
            print(f"⚠️ Submit not confirmed (pass {attempt+1}). Retrying…")
            logger.info(f"⚠️ Submit not confirmed (pass {attempt+1}). Retrying…")
            time.sleep(1.0)


def try_open_job_detail(job_title: str):
    try:
        els = driver.find_elements(By.XPATH,
            f"//a[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{job_title.lower()}')]")
        if els:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", els[0])
            time.sleep(0.4)
            els[0].click(); time.sleep(2.5)
            return True
    except Exception:
        pass
    return False

# ---------- LLM utilities (ported from your universal agent) ----------
def call_openai_api(prompt: str, model="gpt-4o-mini"):
    try:
        resp = client.chat.completions.create(model=model, temperature=0,
            messages=[{"role":"user","content":prompt}]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ OpenAI API error: {e}")
        logger.error(f"❌ OpenAI API error: {e}")
        return ""

def get_dynamic_answer(question_text, user_profile, options=None):
    prompt = f"""
You are an intelligent job-application assistant.
User profile:
{json.dumps(user_profile, indent=2)}
Question: "{question_text}"
{f"Available options: {json.dumps(options, indent=2)}" if options else ""}
Return ONLY the best value to enter. If none, return N/A.
"""
    out = call_openai_api(prompt)
    return out if out else "N/A"

def scrape_form_fields():
    # broad net for inputs/selects/customs
    elements = driver.find_elements(By.XPATH, """
        //*[self::input or self::textarea or self::select or 
           @role='textbox' or @role='combobox' or @role='listbox' or
           contains(@class,'input') or contains(@class,'field') or
           contains(@class,'form-control') or @data-testid='input-field']
    """)
    fields = {}
    for el in elements:
        try:
            if not (el.is_displayed() and el.is_enabled()): 
                continue
            fid   = el.get_attribute("id") or ""
            fname = el.get_attribute("name") or ""
            ph    = el.get_attribute("placeholder") or ""
            aria  = el.get_attribute("aria-label") or ""
            test  = el.get_attribute("data-testid") or ""
            ftype = el.get_attribute("type") or ""
            # best CSS selector we can synthesize
            selector = (
                f"[data-testid='{test}']" if test else
                (f"#{fid}" if fid and ":" not in fid and not fid.isdigit() else "") or
                (f"[name='{fname}']" if fname else "") or
                (f"[placeholder='{ph}']" if ph else "") or
                (f"[aria-label='{aria}']" if aria else "")
            )
            if not selector: 
                continue
            fields[selector] = {
                "id": fid, "name": fname, "placeholder": ph,
                "aria_label": aria, "type": ftype, "testid": test
            }
        except Exception:
            continue
    return fields

def ask_llm_to_match_fields(scraped_fields, user_details):
    fields_info = {k: v for k, v in scraped_fields.items()}
    prompt = f"""
Match form fields to user detail keys.

Fields:
{json.dumps(fields_info, indent=2)}
User Details keys available:
{list(user_details.keys())}

Rules:
- Prefer: data-testid > aria-label > placeholder > name > id
- Typical mappings: first_name/last_name/name/email/phone/location/work_authorization etc.
- Return JSON mapping: {{ "CSS_SELECTOR": "user_detail_key" }}.
"""
    resp = call_openai_api(prompt)
    try:
        return json.loads(resp) if resp else {}
    except json.JSONDecodeError:
        print(f"⚠️ LLM mapping parse failed: {resp}")
        logger.error(f"⚠️ LLM mapping parse failed: {resp}")
        return {}

def fill_fields_from_mapping(mapping, user_details):
    filled = set()
    for selector, detail_key in mapping.items():
        if selector in filled: 
            continue
        value = user_details.get(detail_key, "")
        if not value:
            value = get_dynamic_answer(f"What value should go in '{selector}'?", user_details)
        if not value or value == "N/A":
            continue
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.25)
            tag = el.tag_name
            typ = el.get_attribute("type") or ""
            if tag == "select":
                try:
                    Select(el).select_by_visible_text(value)
                except:
                    opts = [o.text.strip() for o in Select(el).options if o.text.strip()]
                    if value in opts:
                        Select(el).select_by_visible_text(value)
                    elif len(opts) > 1:
                        Select(el).select_by_index(1)
            elif typ == "file":
                path = os.path.abspath(user_details.get("resume_path",""))
                if path and os.path.exists(path):
                    el.send_keys(path)
            elif typ in ["checkbox","radio"]:
                if not el.is_selected():
                    el.click()
            else:
                try: el.clear()
                except: pass
                for ch in str(value):
                    el.send_keys(ch); time.sleep(0.02)
            filled.add(selector)
            print(f"✅ Filled {selector} with {value}")
            logger.info(f"✅ Filled {selector} with {value}")
        except Exception as e:
            print(f"❌ Could not fill {selector}: {e}")
            logger.error(f"❌ Could not fill {selector}: {e}")
    return filled

def fill_remaining_fields_smart(user_details, already_filled):
    # dynamic pass over anything still visible/enabled
    elements = driver.find_elements(By.XPATH, "//input | //textarea | //select | //div[@role='combobox' or @role='listbox']")
    for el in elements:
        try:
            if not (el.is_displayed() and el.is_enabled()): 
                continue
            # synthesize selector again
            fid = el.get_attribute("id") or ""
            fname = el.get_attribute("name") or ""
            ph = el.get_attribute("placeholder") or ""
            aria = el.get_attribute("aria-label") or ""
            selector = (f"[name='{fname}']" if fname else f"#{fid}" if fid else f"[placeholder='{ph}']" if ph else f"[aria-label='{aria}']" if aria else "")
            if not selector or selector in already_filled: 
                continue

            # label text (for better LLM answers)
            label_text = driver.execute_script("""
                let el = arguments[0];
                const c = el.closest('div');
                const lab = (c && (c.querySelector('label, .form-label, span, legend, p, h3'))) || null;
                return lab ? lab.innerText.trim() : '';
            """, el) or aria or ph or fname or fid or "Unknown Field"

            # handle select / custom select / file / checkboxes
            tag = el.tag_name
            typ = el.get_attribute("type") or ""
            if tag == "select":
                opts = [o.text.strip() for o in Select(el).options if o.text.strip()]
                if opts:
                    value = get_dynamic_answer(label_text, user_details, opts)
                    try:
                        if value in opts:
                            Select(el).select_by_visible_text(value)
                        else:
                            Select(el).select_by_index(1 if len(opts) > 1 else 0)
                        already_filled.add(selector)
                        print(f"✅ Selected {label_text} -> {value}")
                        logger.info(f"✅ Selected {label_text} -> {value}")
                        continue
                    except Exception: pass

            if el.get_attribute("role") == "combobox" or el.get_attribute("aria-haspopup") == "listbox":
                try:
                    el.click(); time.sleep(0.2)
                    opts = WebDriverWait(driver, 5).until(
                        EC.visibility_of_any_elements_located((By.XPATH, "//div[@role='option']|//li[@role='option']|//div[contains(@class,'select__option')]"))
                    )
                    choices = [o.text.strip() for o in opts if o.text.strip()]
                    value = get_dynamic_answer(label_text, user_details, choices)
                    matched = False
                    for o in opts:
                        if value.lower() in (o.text or "").strip().lower():
                            o.click(); matched = True; break
                    if not matched and opts:
                        opts[0].click()
                    already_filled.add(selector)
                    print(f"✅ Picked (custom) {label_text} -> {value}")
                    logger.info(f"✅ Picked (custom) {label_text} -> {value}")
                    continue
                except Exception:
                    pass

            if typ == "file":
                path = os.path.abspath(user_details.get("resume_path",""))
                if path and os.path.exists(path):
                    el.send_keys(path); already_filled.add(selector)
                    print(f"✅ Uploaded resume for {label_text}")
                    logger.info(f"✅ Uploaded resume for {label_text}")
                    continue

            if typ in ["checkbox","radio"] and not el.is_selected():
                el.click(); already_filled.add(selector)
                print(f"✅ Checked {label_text}")
                logger.info(f"✅ Checked {label_text}")
                continue

            # regular input/textarea
            value = get_dynamic_answer(label_text, user_details)
            if value and value != "N/A":
                try: el.clear()
                except: pass
                for ch in str(value):
                    el.send_keys(ch); time.sleep(0.02)
                already_filled.add(selector)
                print(f"✅ Filled {label_text} -> {value}")
                logger.info(f"✅ Filled {label_text} -> {value}")
        except StaleElementReferenceException:
            continue
        except Exception as e:
            print(f"⚠️ Skipped a field: {e}")
            logger.error(f"⚠️ Skipped a field: {e}")

def try_click_submit():
    try:
        btn = WebDriverWait(driver, 8).until(EC.presence_of_element_located((
            By.XPATH,
            "//button[not(@disabled) and (contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'submit') "
            " or contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply'))] | "
            "//input[@type='submit' and not(@disabled)]"
        )))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.3)
        start = driver.current_url
        try: btn.click()
        except: driver.execute_script("arguments[0].click();", btn)
        try:
            WebDriverWait(driver, 6).until(lambda d: d.current_url != start)
            return True
        except:
            try:
                WebDriverWait(driver, 5).until(EC.presence_of_element_located((
                    By.XPATH, "//*[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'thank you') or contains(.,'submitted')]"
                )))
                return True
            except:
                return False
    except Exception:
        return False
    
    

# ---------- Main job flow ----------
def process_indeed_job(job_link, user_details):
    logger.info(f"\n🔗 Processing job: {job_link}")
    print(f"\n🔗 Processing job: {job_link}")
    # Reuse the same driver here
    try:
        driver = None  # Initialize driver first

        driver = get_chrome_driver_with_proxy()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        driver.get(job_link)
        time.sleep(5)  # allow full page load
    except Exception as e:
        logger.error(f"❌ Could not open job link {job_link} : {e}")
        return

    # Extract company & title from Indeed detail
    try: title = driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
    except: title = ""
    company = ""
    for xp in [
        "//a[contains(@href,'/cmp/')]", "//h2//a",
        "//div[contains(@class,'InlineCompanyRating')]//span",
        "//div[contains(@class,'jobsearch-CompanyInfo')]//a|//div[contains(@class,'jobsearch-CompanyInfo')]//span"
    ]:
        try:
            company = driver.find_element(By.XPATH, xp).text.strip()
            if company: break
        except: pass
    print(f"🏢 Company: {company} | 💼 {title}")
    logger.info(f"🏢 Company: {company} | 💼 {title}")

    if not company:
        print("❌ No company name. Skipping."); return

    print("🔍 Resolving employer career site...")
    logger.info("🔍 Resolving employer career site...")
    career = find_employer_career_url(company)
    if not career:
        print("❌ Could not resolve career URL."); return

    print(f"➡️ Opening career site: {career}")
    logger.info(f"➡️ Opening career site: {career}")
    driver.get(career); time.sleep(3)

    if title:
        try_open_job_detail(title)

    # LLM mapping → fill; then smart pass; try submit (repeat up to 3)
    for attempt in range(3):
        fields = scrape_form_fields()
        mapping = ask_llm_to_match_fields(fields, user_details) if fields else {}
        filled = fill_fields_from_mapping(mapping, user_details) if mapping else set()
        fill_remaining_fields_smart(user_details, filled)
        if try_click_submit():
            print("✅ Submission likely succeeded.")
            logger.info("✅ Submission likely succeeded.")
            break
        print(f"⚠️ Submit not confirmed (pass {attempt+1}). Retrying…")
        logger.info(f"⚠️ Submit not confirmed (pass {attempt+1}). Retrying…")
        time.sleep(1.2)

def run_from_indeed_search(user_details):
    driver.get(INDEED_SEARCH_URL); time.sleep(4)
    if check_for_captcha():
        print("⚠️ CAPTCHA detected — reloading…")
        logger.info("⚠️ CAPTCHA detected — reloading…")
        time.sleep(2); driver.get(INDEED_SEARCH_URL)
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "mosaic-provider-jobcards")))
    except TimeoutException:
        WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, ".jobTitle a, a[aria-label^='Job title'], a.jcs-JobTitle")
        ))
    scroll_until_jobs_loaded()
    cards = driver.find_elements(By.XPATH, "//a[contains(@class,'jcs-JobTitle')]") or \
            driver.find_elements(By.CSS_SELECTOR, ".jobTitle a, a[aria-label^='Job title']")
    links = [a.get_attribute("href") for a in cards if a.get_attribute("href")]
    for link in links[:MAX_JOBS]:
        process_indeed_job(link, user_details)

# ---------- Entrypoint ----------
def main(candidate_id: int | None = None):
    global driver, wait
    driver = uc.Chrome(version_main=138, options=options)
    wait = WebDriverWait(driver, WAIT_SECONDS)

    # ----- Load user/candidate/jobs from DB (fallback to JSON if needed)
    user_details = {}
    job_urls = []

    with app.app_context():
        if candidate_id:
            cand = Candidate.query.get(candidate_id)
            if not cand:
                print(f"❌ Candidate {candidate_id} not found. Falling back to local JSON.")
                logger.info(f"❌ Candidate {candidate_id} not found. Falling back to local JSON.")
            else:
                # Recruiter (user) who owns the candidate
                recruiter = User.query.filter_by(id=cand.recruiter_id).first()
                # Collect candidate-specific job links if you store them
                jobs = Job.query.filter_by(candidate_id=candidate_id).all()
                job_urls = [j.link for j in jobs if j.link and j.link.startswith("http")]

                user_details = {
                    "first_name": getattr(recruiter, "first_name", "") or "",
                    "last_name":  getattr(recruiter, "last_name", "") or "",
                    "email":      getattr(recruiter, "email", "") or "",
                    "phone":      getattr(recruiter, "phone", "") or "",
                    "resume_path": getattr(cand, "resume_path", "") or "",
                    "work_authorization": getattr(cand, "work_authorization", "") or "",
                    "preferred_location": getattr(cand, "preferred_location", "") or "",
                    "key_skills": getattr(cand, "key_skills", "") or "",
                    "employment": getattr(cand, "employment", "") or "",
                    "education": getattr(cand, "education", "") or "",
                    "certifications": getattr(cand, "certifications", "") or "",
                    "projects": getattr(cand, "projects", "") or "",
                }

        if not user_details:
            # Fallback to local JSON (keeps your current behavior if DB not set)
            with open("user_details_updated.json","r",encoding="utf-8") as f:
                user_details = json.load(f)

    # If DB had jobs for this candidate, use those; otherwise scrape Indeed
    if job_urls:
        print(f"🚀 Loaded {len(job_urls)} job URLs from DB for candidate {candidate_id}")
        logger.info(f"🚀 Loaded {len(job_urls)} job URLs from DB for candidate {candidate_id}")
        for url in job_urls[:MAX_JOBS]:
            process_indeed_job(url, user_details)
    else:
        print("ℹ️ No DB jobs found; running Indeed search flow.")
        logger.info("ℹ️ No DB jobs found; running Indeed search flow.")
        run_from_indeed_search(user_details)

    print("\n✅ Finished processing jobs.")
    logger.info("\n✅ Finished processing jobs.")
    try: driver.quit()
    except: pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indeed → ATS auto-applier")
    parser.add_argument("--mode", choices=["db", "indeed"], default="db",
                        help="db = run using jobs from database; indeed = run Indeed search flow")
    parser.add_argument("--candidate-id", type=int, help="Candidate ID for DB mode")
    args = parser.parse_args()

    # Stealth Chrome once
    driver = uc.Chrome(version_main=138, options=options)
    wait = WebDriverWait(driver, WAIT_SECONDS)

    if args.mode == "indeed":
        print("➡️ Running in INDEED mode (manual search flow)")
        logger.info("➡️ Running in INDEED mode (manual search flow)")
        # local JSON fallback profile if DB not needed
        try:
            with open("user_details_updated.json","r",encoding="utf-8") as f:
                user_details = json.load(f)
        except Exception:
            user_details = {}
        run_from_indeed_search(user_details)
        print("\n✅ Finished INDEED mode.")
        logger.info("\n✅ Finished INDEED mode.")
        try: driver.quit()
        except: pass
        raise SystemExit(0)

    # DB mode
    cand_id = args.candidate_id
    if not cand_id:
        # interactive fallback
        raw = input("Enter Candidate ID (or press Enter to switch to Indeed mode): ").strip()
        if not raw:
            print("ℹ️ No Candidate ID provided. Switching to INDEED mode.")
            logger.info("ℹ️ No Candidate ID provided. Switching to INDEED mode.")
            try:
                with open("user_details_updated.json","r",encoding="utf-8") as f:
                    user_details = json.load(f)
            except Exception:
                user_details = {}
            run_from_indeed_search(user_details)
            print("\n✅ Finished INDEED mode.")
            logger.info("\n✅ Finished INDEED mode.")
            try: driver.quit()
            except: pass
            raise SystemExit(0)
        cand_id = int(raw)

    # DB-driven run
    print(f"➡️ Running in DB mode for candidate {cand_id}")
    logger.info(f"➡️ Running in DB mode for candidate {cand_id}")
    with app.app_context():
        user_details, job_urls = load_profile_and_jobs(cand_id)

    if not job_urls:
        print("⚠️ No jobs found in DB for this candidate.")
        logger.info("⚠️ No jobs found in DB for this candidate.")
    else:
        print(f"🚀 Loaded {len(job_urls)} job URLs from DB")
        logger.info(f"🚀 Loaded {len(job_urls)} job URLs from DB")
        for url in job_urls[:MAX_JOBS]:
            process_job_url(url, user_details)

    print("\n✅ Finished DB mode.")
    logger.info("\n✅ Finished DB mode.")
    try: driver.quit()
    except: pass
