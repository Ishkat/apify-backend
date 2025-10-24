# Updated for AWS EC2 — callable import-safe version
# Original LinkedIn automation preserved

import logging
from flask import current_app
from models import Candidate, Job
from selenium import webdriver

from models import db
from datetime import datetime
import datetime

from selenium.webdriver.support.ui import WebDriverWait

MAX_JOBS = 5
WAIT_SECONDS = 15

# ---- Universal form filler (dropdowns, radios, checkboxes, combobox) ----
from selenium.webdriver.support.ui import Select

# Configure logging
logger = logging.getLogger(__name__)

def run_linkedin_direct(job_url: str, user_json_path: str = "user_details.json"):
    logger.info("Enter run_linkedin_direct function")
    """
    Opens a single LinkedIn job URL and runs the existing automation.
    Does NOT touch your DB or Flask app—pure one-off test.
    """
    # 1) Load user details (same format your file already expects)
    with open(user_json_path, "r", encoding="utf-8") as f:
        user_details = json.load(f)

    # 2) Start browser, go to the URL, and run the existing pipeline
    driver = webdriver.Chrome()
    driver.maximize_window()
    try:
        time.sleep(4)
    finally:
        driver.quit()


def _norm_txt(s): 
    import re; return re.sub(r"\s+", " ", (s or "").strip()).lower()

def _best_match(options, target):
    t = _norm_txt(target)
    for i, o in enumerate(options):
        o2 = _norm_txt(o)
        if o2 == t: return i
    for i, o in enumerate(options):
        if _norm_txt(o).startswith(t): return i
    for i, o in enumerate(options):
        if t in _norm_txt(o): return i
    return None

class FormFiller:
    logger.info("Enter FormFiller class")
    def __init__(self, driver, wait):
        self.d = driver; self.w = wait

    def _visible(self, el):
        try: return el.is_displayed() and el.is_enabled()
        except: return False

    def _labels_for(self, el):
        # try nearby <label> / aria-label / placeholder
        lbl = el.get_attribute("aria-label") or el.get_attribute("placeholder") or ""
        if lbl: return lbl
        try:
            lbl = self.d.execute_script("""
                let e=arguments[0], c=e.closest('div, section, fieldset');
                let lab = c && (c.querySelector('label, .form-label, legend, p, h3, span'));
                return lab ? lab.innerText.trim() : '';
            """, el)
        except: lbl=""
        return lbl or (el.get_attribute("name") or el.get_attribute("id") or "")

    def _type_like_human(self, el, value):
        try: el.clear()
        except: pass
        for ch in str(value):
            el.send_keys(ch)

    def _set_select_single(self, select_el, value):
        logger.info("Enter _set_select_single function")
        try:
            sel = Select(select_el)
            opts = [o.text.strip() for o in sel.options if o.text.strip()]
            idx = _best_match(opts, value)
            if idx is None:
                if len(opts) > 1: sel.select_by_index(1)
                else: sel.select_by_index(0)
            else:
                sel.select_by_index(idx)
            return True
        except: return False

    def _set_select_multi(self, select_el, values):
        logger.info("Enter _set_select_multi function")
        try:
            sel = Select(select_el)
            if not sel.is_multiple: return False
            try: sel.deselect_all()
            except: pass
            opts = [o.text.strip() for o in sel.options if o.text.strip()]
            ok = False
            for v in (values if isinstance(values,(list,tuple,set)) else [values]):
                idx = _best_match(opts, v)
                if idx is not None:
                    sel.select_by_index(idx); ok = True
            return ok
        except: return False

    def _set_custom_combo(self, root, value):
        # handles React-Select / Select2 / ARIA combobox
        try:
            root.click()
            import time; time.sleep(0.3)
            try:
                inp = root.find_element("css selector", "input")
            except:
                inp = root
            self._type_like_human(inp, value)
            time.sleep(0.4)
            options = self.d.find_elements("css selector",
                "[role='option'], .select2-results__option, .Select-option, [data-testid='option']")
            if not options:
                inp.send_keys("\n"); return True
            texts = [o.text.strip() for o in options if o.text.strip()]
            idx = _best_match(texts, value)
            (options[idx] if idx is not None else options[0]).click()
            return True
        except: return False

    def fill_all(self, mapping: dict):
        logger.info("Enter fill_all function")
        """
        mapping: {'first name': 'John', 'work authorization': 'Citizen', ...}
        Returns count of fields filled.
        """
        filled = 0
        controls = self.d.find_elements("css selector",
            "select, input, textarea, [role='combobox'], [role='listbox'], button[aria-haspopup], .select2, .Select-control")
        # Try to fill per mapping key
        for field, value in mapping.items():
            target = _norm_txt(field)
            for el in controls:
                try:
                    if not self._visible(el): 
                        continue
                    lbl = _norm_txt(self._labels_for(el))
                    tag = (el.tag_name or "").lower()
                    typ = (el.get_attribute("type") or "").lower()
                    role = (el.get_attribute("role") or "").lower()
                    cls  = (el.get_attribute("class") or "").lower()

                    # choose candidates by fuzzy label match
                    if target and (target in lbl or any(tok in lbl for tok in target.split())):
                        if tag == "select":
                            ok = self._set_select_multi(el, value) or self._set_select_single(el, value)
                        elif typ == "checkbox":
                            if not el.is_selected(): el.click(); ok=True
                            else: ok=True
                        elif typ == "radio":
                            ok=False  # radios set as a group elsewhere
                        elif role in ("combobox","listbox") or "select2" in cls or "select-control" in cls:
                            ok = self._set_custom_combo(el, value)
                        elif typ == "file":
                            import os; path=os.path.abspath(str(value))
                            ok=False
                            if os.path.exists(path):
                                el.send_keys(path); ok=True
                        else:
                            self._type_like_human(el, value); ok=True
                        if ok: filled += 1; break
                except: 
                    continue
        return filled

def run_linkedin_for_candidate(candidate_id, flask_app=None):
    logger.info(f"Enter run_linkedin_for_candidate function : {candidate_id}")
    global driver
    driver = get_chrome_driver()
    user_details = {}  # TODO: load user details for candidate_id
    process_application(user_details)

    global app
    if flask_app is not None:
        app = flask_app
    elif 'app' not in globals():
        try:
            from flask import current_app
            app = current_app._get_current_object()
        except RuntimeError:
            raise RuntimeError(
                "No Flask app available. Call run_linkedin_for_candidate(candidate_id, flask_app=app)"
            )

    with current_app.app_context():
        candidate = Candidate.query.get(candidate_id)
        if not candidate:
            raise RuntimeError(f"Candidate {candidate_id} not found")
        
                # build user_details from DB (no JSON)
        first, *rest = (candidate.name or "").strip().split()
        last = " ".join(rest) if rest else ""
        user_details = {
            "first_name": first or "",
            "last_name": last or "",
            "email": candidate.email or "",
            "phone": candidate.phone or "",
            "location": candidate.preferred_location or (candidate.state or ""),
            "education": candidate.education or "",
            "employment": candidate.employment or "",
            "key_skills": candidate.key_skills or "",
            "resume": candidate.resume_path or "",  # use this instead of RESUME_PATH
        }

        job = Job.query.filter_by(candidate_id=candidate_id, source="linkedin", status="queued") \
                       .order_by(Job.created_at.asc()).first()
        job_url = job.link if job else None

    if not job_url:
        current_app.logger.info(f"[LinkedIn] No queued jobs for candidate {candidate_id}")
        logger.info(f"[LinkedIn] No queued jobs for candidate {candidate_id}")
        return {"status": "idle", "jobs_processed": 0}

    driver = webdriver.Chrome()
    driver.maximize_window()
    wait = WebDriverWait(driver, WAIT_SECONDS)

    try:
        time.sleep(4)
        success = False
        try:
            success = click_easy_apply()
        except Exception:
            success = False

        with current_app.app_context():
            j = Job.query.filter_by(link=job_url).first()
            if j:
                if success:
                    j.status = "Applied"
                else:
                    j.status = "Retry"
            db.session.commit()

        time.sleep(4)  # Let the page load

        # --- Try clicking 'Company website' if available ---
        clicked = False
        deadline = time.time() + 8  # try for ~8 seconds
        while time.time() < deadline and not clicked:
            try:
                # case-insensitive search anywhere in the modal/page
                link_nodes = driver.find_elements(
                    By.XPATH,
                    "//a[contains(translate(normalize-space(.),"
                    " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                    " 'company website')]"
                )
                if link_nodes:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link_nodes[0])
                    time.sleep(0.3)
                    try:
                        link_nodes[0].click()
                    except Exception:
                        # fall back to JS click if needed
                        driver.execute_script("arguments[0].click();", link_nodes[0])
                    print("✅ Clicked: Company website (bypassed LinkedIn login)")
                    logger.info("✅ Clicked: Company website (bypassed LinkedIn login)")
                    clicked = True
                    # wait for redirect off linkedin.com
                    WebDriverWait(driver, 10).until(lambda d: 'linkedin.com' not in d.current_url)
                    time.sleep(2)
                    # optional: run external application automation now
                    try:
                        process_external_application(driver, user_details)
                    except Exception as e:
                        print(f"External apply flow error: {e}")
                        logger.error(f"External apply flow error: {e}")
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not clicked:
            print("ℹ️ Company website link not found; proceeding with Easy Apply flow.")
            logger.info("ℹ️ Company website link not found; proceeding with Easy Apply flow.")

    finally:
        driver.quit()



# ==== Original LinkedIn logic preserved below ====
import csv
import json
import os
import time
import requests
from selenium import webdriver
from urllib.parse import urlparse, parse_qs, unquote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchWindowException
from selenium.common.exceptions import (NoSuchElementException, 
                                      ElementClickInterceptedException,
                                      TimeoutException, StaleElementReferenceException)
from openai import OpenAI
import re
import openai
from urllib.parse import urlparse

# --- OPENAI API CONFIGURATION ---
openai.api_key = ""

# --- CONFIGURATION ---
MAX_RETRIES = 3
VISUAL_FALLBACK = True

try:
    from PIL import Image
    import pytesseract
    import cv2
    import numpy as np
    VISUAL_FALLBACK_AVAILABLE = True
except ImportError:
    VISUAL_FALLBACK_AVAILABLE = False
    if VISUAL_FALLBACK:
        print("⚠️ Visual fallback dependencies not installed. Run: pip install pillow pytesseract opencv-python")

# --- UTILITY FUNCTIONS ---
def call_openai_api(prompt):
    try:
        client = OpenAI(api_key=openai.api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error fetching answer from OpenAI API: {e}")
        return ""
    
def get_dynamic_answer(question_text, user_profile, options=None):
    logger.info("Enter get_dynamic_answer function")
    prompt = (
        f"You are an intelligent job application assistant.\n"
        f"Here is the user's profile:\n"
        f"{json.dumps(user_profile, indent=2)}\n"
        f"Question: \"{question_text}\"\n"
        f"{f'Available options: {json.dumps(options, indent=2)}' if options else ''}\n"
        "Please provide ONLY the most suitable value for this question based on the user profile and context.\n"
        "For dropdowns, select an option from the provided list that best matches the profile or question intent.\n"
        "Return 'N/A' if no suitable value is found."
    )
    return call_openai_api(prompt) or "N/A"

def find_fields_visually(driver):
    logger.info("Enter find_fields_visually function")
    if not VISUAL_FALLBACK_AVAILABLE:
        return []
    
    try:
        from PIL import Image
        import pytesseract
        import io
        import cv2
        import numpy as np
        
        print("Attempting visual field detection...")
        
        # Take screenshot of visible area
        screenshot = driver.get_screenshot_as_png()
        img = Image.open(io.BytesIO(screenshot))
        img_np = np.array(img)
        
        # Convert to grayscale
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        
        # Use OCR to find text elements
        text_data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
        
        # Find all input fields
        fields = driver.find_elements(By.XPATH, "//input | //textarea | //div[@role='textbox']")
        found_fields = []
        
        for i, text in enumerate(text_data['text']):
            if text.strip() and int(text_data['conf'][i]) > 60:  # Minimum confidence
                x = text_data['left'][i]
                y = text_data['top'][i]
                w = text_data['width'][i]
                h = text_data['height'][i]
                
                # Check if text is near any input field
                for field in fields:
                    try:
                        field_location = field.location
                        field_size = field.size
                        
                        # Check if label is above or left of field
                        if (abs(x - field_location['x']) < 100 and 
                            abs(y - field_location['y']) < 50):
                            
                            found_fields.append({
                                'field': field,
                                'label': text.strip(),
                                'position': (x, y)
                            })
                    except StaleElementReferenceException:
                        continue
        
        print(f"👁️ Found {len(found_fields)} fields visually")
        return found_fields
        
    except Exception as e:
        print(f"⚠️ Visual detection failed: {e}")
        return []
    


# --- CONFIGURATION ---
RESUME_PATH = "resume.pdf"
USER_JSON = "user_details.json"
JOBS_CSV = "jobs.csv"
MAX_RETRIES = 3

# --- LOAD USER DETAILS ---
with open(USER_JSON, 'r', encoding='utf-8') as f:
    user_details = json.load(f)

linkedin_email = user_details.get("email")
linkedin_password = user_details.get("password")
phone_number = user_details.get("phone", "")
first_name = user_details.get("first_name", "")
last_name = user_details.get("last_name", "")

if not linkedin_email or not linkedin_password:
    print("Please add your LinkedIn email and password to user_details.json.")
    exit()

# --- READ FIRST JOB LINK ---
with open(JOBS_CSV, newline='', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader)  # Skip header
    first_link = next(reader)[0]

# --- START SELENIUM BROWSER ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Global driver instance
driver = None

import subprocess
import random
import undetected_chromedriver as uc

def get_chrome_driver():
    logger.info("Entry get_chrome_driver function.")
    # Detect installed Chromium major version
    try:
        result = subprocess.run(
            ["/usr/bin/chromium", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        version_str = result.stdout.strip()  # e.g. "Chromium 140.0.7261.57"
        version_main = int(version_str.split()[1].split(".")[0])
    except Exception as e:
        version_main = 139  # fallback default
        print(f"⚠️ Could not auto-detect Chromium version, falling back to {version_main}: {e}")

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")

    # 🔑 Add rotating User-Agent that matches detected Chromium version
    user_agents = [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version_main}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version_main}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version_main}.0.0.0 Safari/537.36",
    ]
    ua = random.choice(user_agents)
    options.add_argument(f"--user-agent={ua}")

    driver = uc.Chrome(
        version_main=version_main,
        browser_executable_path="/usr/bin/chromium",
        driver_executable_path="/usr/bin/chromedriver",
        options=options
    )
    logger.info("Exit get_chrome_driver function.")
    return driver

def get_chrome_driver_with_proxy():
    logger.info("Entry get_chrome_driver_with_proxy function.")
    options = uc.ChromeOptions()

    # 🖥 Standard headless safe flags (needed for Apify)
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")

    # 🧠 Detect installed Chromium major version for realistic User-Agent
    try:
        result = subprocess.run(
            ["/usr/bin/chromium", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        version_str = result.stdout.strip()  # e.g. "Chromium 140.0.7261.57"
        version_main = int(version_str.split()[1].split(".")[0])
    except Exception as e:
        version_main = 120  # fallback if detection fails
        print(f"⚠️ Could not detect Chromium version, falling back to {version_main}: {e}")

    # 🎭 Random realistic User-Agent
    user_agents = [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version_main}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version_main}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version_main}.0.0.0 Safari/537.36",
    ]
    options.add_argument(f"--user-agent={random.choice(user_agents)}")

    # 🌐 Use Apify Proxy (hardcoded password)
    apify_proxy_password = ""
    proxy_url = f"http://auto:{apify_proxy_password}@proxy.apify.com:8000"
    options.add_argument(f"--proxy-server={proxy_url}")

    # 🚀 Launch undetected Chrome
    driver = uc.Chrome(
        browser_executable_path="/usr/bin/chromium",
        driver_executable_path="/usr/bin/chromedriver",
        options=options
    )

    logger.info("Exit get_chrome_driver_with_proxy function.")
    return driver


def is_linkedin(u: str) -> bool:
    try: return "linkedin." in urlparse(u).netloc
    except: return False

def is_authwall(u: str) -> bool:
    return "linkedin.com/authwall" in u

def normalize_linkedin_url(u: str) -> str:
    if "linkedin.com/comm/redirect" in u:
        qs = parse_qs(urlparse(u).query)
        target = qs.get("url", [""])[0]
        return unquote(target) or u
    if is_authwall(u):
        qs = parse_qs(urlparse(u).query)
        for key in ("url", "sessionRedirect"):
            if key in qs:
                return unquote(qs[key][0])
    return u


# --- AUTOMATE LINKEDIN LOGIN ---
# def linkedin_login():
#     print("Navigating to LinkedIn login page...")
#     driver.get("https://www.linkedin.com/login")
    
#     try:
#         WebDriverWait(driver, 10).until(
#             EC.presence_of_element_located((By.ID, "username"))
#         )
#         email_field = driver.find_element(By.ID, "username")
#         pass_field = driver.find_element(By.ID, "password")
#         email_field.send_keys(linkedin_email)
#         pass_field.send_keys(linkedin_password)
#         login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
#         login_btn.click()
#         print("Submitted login form.")
#     except Exception as e:
#         print(f"Login failed: {e}")
#         driver.quit()
#         exit()

# linkedin_login()
# time.sleep(3)  # Allow for manual CAPTCHA/2FA

# # --- NAVIGATE TO JOB LINK ---


# --- CLICK EASY APPLY BUTTON ---
def click_easy_apply():
    print("Attempting to click Easy Apply button...")
    logger.info("Attempting to click Easy Apply button...")
    selectors = [
        "button.jobs-apply-button",
        "button[data-control-name='apply']",
        "button.jobs-s-apply",
        "//button[contains(., 'Apply')]"
    ]
    
    for attempt in range(MAX_RETRIES):
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".jobs-details"))
            )
            for selector in selectors:
                try:
                    time.sleep(2)
                    button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH if selector.startswith("//") else By.CSS_SELECTOR, selector))
                    )
                    driver.execute_script("window.scrollTo(0, arguments[0].getBoundingClientRect().top - 200);", button)
                    time.sleep(2)
                    try:
                        driver.find_element(By.CSS_SELECTOR, "button[aria-label='Dismiss']").click()
                        time.sleep(2)
                    except:
                        pass
                    button.click()
                    print("Successfully clicked Easy Apply button.")
                    logger.info("Successfully clicked Easy Apply button.")
                    return True
                except Exception as e:
                    print(f"Attempt {attempt + 1}, selector '{selector}' failed: {str(e)[:100]}...")
                    logger.error(f"Attempt {attempt + 1}, selector '{selector}' failed: {str(e)[:100]}...")
            time.sleep(3)
        except Exception as e:
            print(f"Easy Apply attempt {attempt + 1} failed: {e}")
            logger.error(f"Easy Apply attempt {attempt + 1} failed: {e}")
    
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button")
        for button in buttons:
            if "apply" in button.text.lower():
                driver.execute_script("arguments[0].click();", button)
                print("Used JavaScript click fallback.")
                logger.info("Used JavaScript click fallback.")
                return True
    except:
        pass
    
    print("All attempts to click Easy Apply failed.")
    logger.info("All attempts to click Easy Apply failed.")
    return False

if not click_easy_apply():
    print("Proceeding..."); time.sleep(1)

# --- HANDLE WINDOW/TAB SWITCHING ---
def switch_to_new_window(original_window):
    print("Checking for new window/tab...")
    time.sleep(3)
    windows = driver.window_handles
    if len(windows) > 1:
        for window in windows:
            if window != original_window:
                driver.switch_to.window(window)
                print(f"Switched to new window: {driver.current_url}")
                return True
    return False

# --- SCRAPE CLICKABLE ELEMENTS WITH CLUSTERING ---
def get_clickable_elements(driver):
    logger.info("Enter get_clickable_elements function")
    elements = []
    sections = [
        ("header", "//header//button|//header//a"),
        ("footer", "//footer//button|//footer//a"),
        ("application-form", "//form//button|//form//a"),
        ("modal", "//div[contains(@class, 'modal')]//button|//div[contains(@class, 'modal')]//a"),
        ("main", "//body//button|//body//a")
    ]
    
    for section_name, xpath in sections:
        try:
            section_elements = driver.find_elements(By.XPATH, xpath)
            for elem in section_elements:
                try:
                    if not (elem.is_displayed() and elem.is_enabled()):
                        continue
                    near_input = bool(elem.find_elements(By.XPATH, ".//preceding::input|.//following::input"))
                    score = 0
                    if elem.is_displayed() and elem.is_enabled():
                        score += 10
                    if section_name == "application-form":
                        score += 8
                    if near_input:
                        score += 5
                    if section_name in ["header", "footer"]:
                        score -= 5
                    if "modal" in section_name:
                        score += 3
                    if elem.get_attribute("tabindex") and int(elem.get_attribute("tabindex")) >= 0:
                        score += 2
                    
                    elements.append({
                        "section": section_name,
                        "button_text": elem.text.strip() or "N/A",
                        "type": elem.get_attribute("type") or "N/A",
                        "visible": elem.is_displayed(),
                        "enabled": elem.is_enabled(),
                        "near_input": near_input,
                        "id": elem.get_attribute("id") or "N/A",
                        "aria-label": elem.get_attribute("aria-label") or "N/A",
                        "href": elem.get_attribute("href") or "N/A" if elem.tag_name == "a" else "N/A",
                        "score": score,
                        "element": elem
                    })
                except StaleElementReferenceException:
                    continue
        except Exception as e:
            print(f"Error scraping section {section_name}: {e}")
    
    elements.sort(key=lambda x: x["score"], reverse=True)
    print(f"Found {len(elements)} clickable elements:")
    for idx, elem in enumerate(elements, 1):
        print(f"Element {idx}: Section={elem['section']}, Text={elem['button_text']}, Score={elem['score']}")
    return elements

# --- LLM BUTTON SELECTION ---
def ask_llm_to_select_button(elements, client):
    logger.info("Enter ask_llm_to_select_button function")
    elements_description = [
        {
            "section": e["section"],
            "button_text": e["button_text"],
            "type": e["type"],
            "visible": e["visible"],
            "enabled": e["enabled"],
            "near_input": e["near_input"],
            "id": e["id"],
            "aria-label": e["aria-label"],
            "href": e["href"],
            "score": e["score"]
        } for e in elements
    ]
    
    prompt = f"""
Choose the best button to proceed with the job application. Here are the options:
{json.dumps(elements_description, indent=2)}
Respond as JSON: {{"index": N, "reason": "your reasoning"}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        resp = json.loads(response.choices[0].message.content.strip())
        index = resp.get("index")
        reason = resp.get("reason", "No reason provided")
        print(f"LLM chose index {index + 1}: {reason}")
        if index < 0 or index >= len(elements):
            print("Invalid index returned by LLM.")
            return None, None
        return index, reason
    except Exception as e:
        print(f"Error fetching LLM decision: {e}")
        return None, None

# --- CLICK ELEMENT WITH RETRY ---
def click_element_by_description(driver, element_description):
    logger.info("Enter click_element_by_description function")
    for attempt in range(MAX_RETRIES):
        try:
            elem = element_description["element"]
            driver.execute_script("arguments[0].scrollIntoView(true);", elem)
            time.sleep(1)
            elem.click()
            print(f"Clicked element: {element_description['button_text']} (Section: {element_description['section']})")
            logger.info(f"Clicked element: {element_description['button_text']} (Section: {element_description['section']})")
            WebDriverWait(driver, 5).until(EC.staleness_of(elem) or EC.presence_of_element_located((By.CSS_SELECTOR, "div")))
            return True
        except Exception as e:
            print(f"Attempt {attempt + 1} failed to click element: {e}")
            logger.error(f"Attempt {attempt + 1} failed to click element: {e}")
            time.sleep(2)
            try:
                # Re-fetch element in case of DOM change
                if element_description["id"] != "N/A":
                    elem = driver.find_element(By.ID, element_description["id"])
                elif element_description["aria-label"] != "N/A":
                    elem = driver.find_element(By.CSS_SELECTOR, f"[aria-label='{element_description['aria-label']}']")
                else:
                    elem = driver.find_element(By.XPATH, f"//{element_description['tag']}[contains(text(), '{element_description['button_text']}')]")
                element_description["element"] = elem
            except:
                print("Element no longer available.")
                logger.error("Element no longer available.")
                return False
    return False

# --- SCRAPE FORM FIELDS ---
def scrape_form_fields(driver):
    print("🔍 Scraping all input/textarea/select elements on page...")
    logger.info("🔍 Scraping all input/textarea/select elements on page...")
    elements = driver.find_elements(By.XPATH, """
        //*[self::input or self::textarea or self::select or 
            @role='textbox' or 
            contains(@class, 'input') or
            contains(@class, 'field') or
            contains(@class, 'form-control') or
            @data-testid='input-field']
    """)
    
    fields = {}
    for field in elements:
        try:
            if not field.is_displayed():
                continue
                
            # Get all possible identifiers
            field_id = field.get_attribute("id") or ""
            field_name = field.get_attribute("name") or ""
            placeholder = field.get_attribute("placeholder") or ""
            aria_label = field.get_attribute("aria-label") or ""
            testid = field.get_attribute("data-testid") or ""
            field_type = field.get_attribute("type") or ""
            
            # Create priority-based selector
            if testid:
                selector = f"[data-testid='{testid}']"
            elif field_id:
                selector = f"#{field_id}"
            elif field_name:
                selector = f"[name='{field_name}']"
            elif aria_label:
                selector = f"[aria-label='{aria_label}']"
            elif placeholder:
                selector = f"[placeholder='{placeholder}']"
            else:
                # Fallback to XPath based on position
                xpath = driver.execute_script("""
                    return document.evaluate(
                        arguments[0], 
                        document, 
                        null, 
                        XPathResult.FIRST_ORDERED_NODE_TYPE, 
                        null
                    ).singleNodeValue;
                """, field)
                selector = f"xpath:{xpath}" if xpath else None
                
            if selector:
                fields[selector] = {
                    "element": field,
                    "id": field_id,
                    "name": field_name,
                    "placeholder": placeholder,
                    "aria_label": aria_label,
                    "type": field_type,
                    "testid": testid
                }
        except Exception as e:
            print(f"⚠️ Failed to process field: {e}")
    
    # If standard detection finds <2 fields, try visual fallback
    if len(fields) < 2 and VISUAL_FALLBACK and VISUAL_FALLBACK_AVAILABLE:
        visual_fields = find_fields_visually(driver)
        for vf in visual_fields:
            selector = f"visual:{vf['label']}"
            fields[selector] = {
                'element': vf['field'],
                'visual_label': vf['label'],
                'type': 'visual_fallback'
            }
    
    print(f"✅ Scraped {len(fields)} fields.")
    return fields
# --- LLM FIELD MAPPING ---
def ask_llm_to_match_fields(scraped_fields, user_details):
    fields_info = {k: {key: val for key, val in v.items() if key != "element"} 
                  for k, v in scraped_fields.items()}
    
    prompt = f"""
Analyze these form fields and match them to user details:
Fields:
{json.dumps(fields_info, indent=2)}

User Details:
{json.dumps(user_details, indent=2)}

Rules:
1. Prioritize matching by: data-testid > aria-label > placeholder > name > id
2. For name fields, look for: 'name', 'first', 'last', 'fullname'
3. For email fields, look for: 'email', 'mail', 'e-mail'
4. Return JSON with field selectors mapped to user detail keys

Example Output:
{{
  "[data-testid='name-input']": "first_name",
  "[aria-label='Email Address']": "email"
}}
"""
    return json.loads(call_openai_api(prompt) or "{}")


# --- FILL FIELDS ---
def fill_fields_from_mapping(driver, mapping, user_details, filled_selectors):
    logger.info("Enter fill_fields_from_mapping function")
    for selector, detail_key in mapping.items():
        if selector in filled_selectors:
            continue
            
        value = user_details.get(detail_key, "")
        if not value:
            continue
            
        try:
            # Handle visual fallback selectors differently
            if selector.startswith('visual:'):
                label = selector.replace('visual:', '')
                value = get_dynamic_answer(f"What should go in the '{label}' field?", user_details)
                if not value:
                    continue
                    
                field = mapping[selector]['element']
                field.clear()
                field.send_keys(value)
                print(f"👁️ Filled (visual) {label} with {value}")
                continue
                
            # Handle special fields
            if detail_key in ['first_name', 'last_name', 'name']:
                if "first" in detail_key:
                    value = user_details['first_name']
                elif "last" in detail_key:
                    value = user_details['last_name']
                else:
                    value = f"{user_details['first_name']} {user_details['last_name']}"
            
            if detail_key == 'email' and "@" not in value:
                print("⚠️ Invalid email format")
                continue
                
            # === Add CSS + XPath support ===
            if selector.startswith("#") or selector.startswith("["):
                fields = driver.find_elements(By.CSS_SELECTOR, selector)
            elif selector.startswith("xpath:"):
                try:
                   xpath = selector.replace("xpath:", "")
                   fields = [driver.find_element(By.XPATH, xpath)]
                except Exception as e:
                    print(f"⚠️ XPath selector failed: {xpath} — {e}")
                    fields = []
            else:
                fields = []            

            if len(fields) == 0:
                continue
            if len(fields) > 1:
                print(f"⚠️ Selector '{selector}' matched multiple elements")
                continue

            field = fields[0]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", field)
            time.sleep(0.3)
            
            if field.tag_name == "select":
                Select(field).select_by_visible_text(value)
            elif field.get_attribute("type") == "file":
                field.send_keys(os.path.abspath(RESUME_PATH))
            else:
                field.clear()
                for char in str(value):
                    field.send_keys(char)
                    time.sleep(0.05)
                    
            print(f"✅ Filled {selector} with {value}")
            filled_selectors.add(selector)
            
        except Exception as e:
            print(f"❌ Failed to fill {selector}: {e}")
# --- DETECT FORM PRESENCE ---
def page_contains_form(driver):
    logger.info("Enter page_contains_form function")
    try:
        form_elements = driver.find_elements(By.XPATH, "//input | //textarea | //select | //div[@role='listbox']")
        return len(form_elements) > 0
    except Exception as e:
        print(f"Error checking for form: {e}")
        return False

# --- FILL DYNAMIC FORM FIELDS ---
# --- FILL DYNAMIC FORM FIELDS ---
def fill_dynamic_form_fields(driver, user_details, filled_selectors):
    logger.info("Enter fill_dynamic_form_fields function")
    elements = driver.find_elements(By.XPATH, "//input | //textarea | //select | //div[@role='listbox']")
    for elem in elements:
        if not elem.is_displayed() or not elem.is_enabled():
            continue
        try:
            # Generate a unique selector
            field_id = elem.get_attribute("id")
            field_name = elem.get_attribute("name")
            placeholder = elem.get_attribute("placeholder")
            aria_label = elem.get_attribute("aria-label")
            field_class = elem.get_attribute("class")
            selector = (
                f"#{field_id}" if field_id and ":" not in field_id else
                f"[name='{field_name}']" if field_name else
                f"[placeholder='{placeholder}']" if placeholder else
                f"[aria-label='{aria_label}']" if aria_label else
                f".{field_class.split()[0]}" if field_class else
                f"div[role='listbox']" if elem.get_attribute("role") == "listbox" else None
            )
            if not selector or selector in filled_selectors:
                print(f"Skipping {selector or 'unknown field'}: Already filled or no valid selector")
                continue

            # Get question text with fallback
            question_text = driver.execute_script("""
                let el = arguments[0];
                let labelEl = el.closest('div').querySelector('label, span, .form-label, legend') || 
                              el.closest('div').querySelector('p, h3') || 
                              el.find_element(By.XPATH, "./preceding-sibling::label");
                return labelEl ? labelEl.innerText.trim() : '';
            """, elem) or aria_label or placeholder or field_name or field_id or "Unknown Field"

            # Handle standard <select> dropdowns
            if elem.tag_name == "select":
                try:
                    driver.execute_script("arguments[0].click();", elem)
                    time.sleep(0.5)  # Wait for options to load
                    select = Select(elem)
                    options = [option.text.strip() for option in select.options if option.text.strip()]
                    if not options:
                        print(f"No options found for dropdown: {question_text}")
                        continue

                    prompt = f"""
                    You are a smart form-filling assistant.
                    User profile:
                    {json.dumps(user_details, indent=2)}
                    Question: {question_text}
                    Options: {json.dumps(options, indent=2)}
                    Choose the best matching option based on the user profile and question context (e.g., work authorization, location).
                    Respond as:
                    {{"value": "selected_option", "reason": "your reasoning"}}
                    If no suitable option is found, return {{"value": "N/A", "reason": "No matching option"}}.
                    """
                    response = call_openai_api(prompt)
                    try:
                        result = json.loads(response) if response else {"value": "N/A", "reason": "No response from LLM"}
                        selected_value = result.get("value", "N/A")
                        reason = result.get("reason", "No reason provided")
                        if selected_value != "N/A" and selected_value in options:
                            select.select_by_visible_text(selected_value)
                            print(f"✅ Selected dropdown option: {question_text} -> {selected_value} (Reason: {reason})")
                            filled_selectors.add(selector)
                        else:
                            print(f"⚠️ No matching dropdown option for {question_text}: {selected_value} (Reason: {reason})")
                    except json.JSONDecodeError:
                        print(f"⚠️ Invalid LLM response for dropdown {question_text}: {response}")
                except Exception as e:
                    print(f"⚠️ Failed to process dropdown for {question_text}: {e}")
                time.sleep(0.5)
                continue

            # Handle custom dropdowns (<div role="listbox"> or similar)
            if elem.get_attribute("aria-haspopup") == "listbox" or elem.get_attribute("role") == "combobox":
                try:
                    value = get_dynamic_answer(question_text, user_details)
                    elem.click()
                    time.sleep(0.5)
                    options = driver.find_elements(By.XPATH, "//div[contains(@class,'select__option') and @role='option'] | //div[@role='option']")
                    matched = False
                    for opt in options:
                        if value.lower() in opt.text.strip().lower():
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", opt)
                            time.sleep(0.2)
                            opt.click()
                            matched = True
                            break
                    if not matched and options:
                        options[0].click()
                    print(f"✅ Filled (custom dropdown): {question_text} -> {value}")
                    filled_selectors.add(selector)
                except Exception as e:
                    print(f"❌ Custom dropdown failed: {question_text} — {e}")
                time.sleep(0.5)
                continue

            # Handle file uploads
            if elem.get_attribute("type") == "file":
                try:
                    elem.send_keys(os.path.abspath(RESUME_PATH))
                    print(f"✅ Resume uploaded to: {question_text}")
                    filled_selectors.add(selector)
                    time.sleep(3)
                except Exception as e:
                    print(f"⚠️ Failed to upload resume for {question_text}: {e}")
                continue

            # Handle regular input/textarea
            value = get_dynamic_answer(f"What value should I fill for '{question_text}'?", user_details)
            if value == "N/A":
                print(f"Skipping {question_text}: No suitable value")
                continue
            if elem.get_attribute("type") == "email" and "@" not in value:
                print(f"⚠️ Invalid email format for {question_text}: {value}")
                continue
            elem.clear()
            for char in value:  # Simulate human typing
                elem.send_keys(char)
                time.sleep(0.1)  # Small delay per character
            print(f"✅ Filled: {question_text} -> {value}")
            filled_selectors.add(selector)
            time.sleep(0.5)  # Delay between fields
        except StaleElementReferenceException:
            print(f"⚠️ Stale element for {question_text}. Skipping.")
        except Exception as e:
            print(f"⚠️ Could not fill {question_text}: {e}")

    # --- Handle location autocomplete ---
    for elem in elements:
        if not elem.is_displayed() or not elem.is_enabled():
            continue
        try:
            field_id = elem.get_attribute("id")
            field_name = elem.get_attribute("name")
            placeholder = elem.get_attribute("placeholder")
            aria_label = elem.get_attribute("aria-label")
            question_text = driver.execute_script("""
                let el = arguments[0];
                let labelEl = el.closest('div').querySelector('label, span, .form-label, legend') || 
                              el.closest('div').querySelector('p, h3') || 
                              el.find_element(By.XPATH, "./preceding-sibling::label");
                return labelEl ? labelEl.innerText.trim() : '';
            """, elem) or aria_label or placeholder or field_name or field_id or "Unknown Field"
            selector = (
                f"#{field_id}" if field_id and ":" not in field_id else
                f"[name='{field_name}']" if field_name else
                f"[placeholder='{placeholder}']" if placeholder else
                f"[aria-label='{aria_label}']" if aria_label else None
            )
            if not selector or selector in filled_selectors:
                continue
            if "location" in question_text.lower() or "city" in question_text.lower():
                value = user_details.get("location", "San Francisco, CA, USA")
                try:
                    elem.clear()
                    elem.send_keys(value)
                    time.sleep(1.5)  # Wait for autocomplete to load
                    dropdown_options = driver.find_elements(By.XPATH, "//div[contains(@class, 'option') or @role='option']")
                    matched = False
                    for opt in dropdown_options:
                        opt_text = opt.text.strip().lower()
                        if value.lower() in opt_text or opt_text in value.lower():
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", opt)
                            time.sleep(0.2)
                            driver.execute_script("arguments[0].click();", opt)
                            print(f"✅ Selected location from autocomplete: {opt.text}")
                            matched = True
                            break
                    if not matched:
                        print("⚠️ No matching location found in dropdown. Leaving value typed.")
                    filled_selectors.add(selector)
                    time.sleep(1)
                except Exception as e:
                    print(f"⚠️ Failed to process location autocomplete: {e}")
        except Exception as e:
            print(f"⚠️ Error processing location field: {e}")

    # Handle Yes/No buttons
    try:
        yes_no_containers = driver.find_elements(By.XPATH, "//div[contains(., 'Yes') and contains(., 'No')]")
        for container in yes_no_containers:
            try:
                question_text = container.text.strip()
                if not question_text or "Submit Application" in question_text:
                    continue
                selector = f"yes_no_{question_text[:30]}"  # Unique selector for Yes/No
                if selector in filled_selectors:
                    print(f"Skipping Yes/No question '{question_text}': Already answered")
                    continue
                answer = get_dynamic_answer(f"For the question '{question_text}', what is the most suitable answer based on the user profile?", user_details, ["Yes", "No"])
                answer_lower = answer.lower().strip()
                if answer_lower not in ['yes', 'no', 'n/a', 'none']:
                    print(f"⚠️ Invalid Yes/No answer for {question_text}: {answer}")
                    continue
                try:
                    button = container.find_element(By.XPATH, f".//button[contains(translate(., 'YESNO', 'yesno'), '{answer_lower}')]")
                    driver.execute_script("arguments[0].scrollIntoView(true);", button)
                    time.sleep(1)
                    button.click()
                    print(f"✅ Clicked '{answer}' for: {question_text}")
                    filled_selectors.add(selector)
                    time.sleep(2)
                except Exception as e:
                    print(f"⚠️ No matching button found for dynamic question '{question_text}': {e}")
            except Exception as e:
                print(f"⚠️ Error processing Yes/No container for '{question_text}': {e}")
    except Exception as e:
        print(f"⚠️ Error processing dynamic Yes/No questions: {e}")

# --- TRY CLICK SUBMIT ---
def try_click_submit(driver):
    logger.info("Enter try_click_submit function")
    for attempt in range(MAX_RETRIES):
        try:
            print(f" Looking for Submit button on page: {driver.current_url} (Attempt {attempt+1})")

            # Wait up to 10s for any button with submit/apply/continue text to appear
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        "//button[contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'submit') or "
                        "contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'apply') or "
                        "contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'next') or "
                        "contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'continue')]"
                    ))
                )
            except Exception:
                print(" No submit-like button appeared within 10s.")
                continue

            # Broaden XPath to include more variations
            submit_buttons = driver.find_elements(By.XPATH, """
                //button[contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'submit') or 
                        contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'apply') or 
                        contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'next') or 
                        contains(translate(., 'SUBMITAPPLYNEXTCONTINUE', 'submitapplynextcontinue'), 'continue')] | 
                //input[@type='submit'] | 
                //button[@type='submit'] | 
                //button[contains(@class, 'submit') or contains(@class, 'apply') or contains(@class, 'next') or contains(@class, 'continue')]
            """)

            print(f"   Found {len(submit_buttons)} potential submit buttons")
            for i, b in enumerate(submit_buttons, 1):
                try:
                    print(f"      [{i}] text='{b.text.strip()}', aria-label='{b.get_attribute('aria-label')}', enabled={b.is_enabled()}, visible={b.is_displayed()}")
                except Exception:
                    continue

            for button in submit_buttons:
                button_text = button.text.lower() if button.text else ''
                if not button.is_displayed() or not button.is_enabled():
                    print(f"Skipping button '{button_text}': Not visible or disabled")
                    continue
                driver.execute_script("arguments[0].scrollIntoView(true);", button)
                time.sleep(1.5)
                try:
                    button.click()
                    print(f"✅ Submit button clicked: {button_text}")
                    WebDriverWait(driver, 5).until(EC.staleness_of(button) or EC.presence_of_element_located((By.CSS_SELECTOR, "div")))
                    time.sleep(2)
                    return True
                except ElementClickInterceptedException:
                    print("⚠️ Click intercepted, attempting JS fallback...")
                    driver.execute_script("arguments[0].click();", button)
                    print(f"✅ Submit button clicked via JS: {button_text}")
                    time.sleep(2)
                    return True
                except Exception as e:
                    print(f"⚠️ Failed to click button '{button_text}': {e}")
            
            # Check for reCAPTCHA
            if "recaptcha" in driver.page_source.lower():
                print("⚠️ reCAPTCHA detected. Please complete it manually and press Enter to continue.")
                input("Press Enter when reCAPTCHA is solved...")
                continue
            print("⚠️ No clickable Submit button found.")
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Failed to locate or click submit: {e}")
            time.sleep(2)
    return False

# --- PROCESS EXTERNAL APPLICATION ---
# --- PROCESS EXTERNAL APPLICATION ---
def process_external_application(driver, user_details):
    print(f"Processing external application: {driver.current_url}")
    logger.info(f"Processing external application: {driver.current_url}")
    client = OpenAI(api_key=openai.api_key)
    filled_selectors = set()  # Track filled fields

    for attempt in range(MAX_RETRIES):
        try:
            if not driver.window_handles:  # Check if browser is still open
                print("⚠️ Browser window closed unexpectedly. Terminating process.")
                return
            if page_contains_form(driver):
                fields = scrape_form_fields(driver)
                if fields:
                    mapping = ask_llm_to_match_fields(fields, user_details)
                    print("🔁 LLM Returned Mapping:")
                    print(json.dumps(mapping, indent=2))
                    fill_fields_from_mapping(driver, mapping, user_details, filled_selectors)
                fill_dynamic_form_fields(driver, user_details, filled_selectors)
            
            time.sleep(5)
            clickable_elements = get_clickable_elements(driver)
            if clickable_elements:
                index, reason = ask_llm_to_select_button(clickable_elements, client)
                if index is not None:
                    if click_element_by_description(driver, clickable_elements[index]):
                        print(f"Clicked button based on LLM choice: {reason}")
                        time.sleep(3)  # Wait for DOM change
                        filled_selectors.clear()  # Reset filled selectors after page change
                        continue
                    else:
                        print("Failed to click LLM-chosen button. Retrying...")
                else:
                    print("LLM failed to select a valid button.")
            
            if try_click_submit(driver):
                break
            
            print(f"Attempt {attempt + 1} completed. Re-scanning DOM...")
            time.sleep(2)
        except NoSuchWindowException:
            print("⚠️ Browser window closed unexpectedly. Terminating process.")
            return
        except Exception as e:
            print(f"⚠️ Error in attempt {attempt + 1}: {e}")
            time.sleep(2)

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Thank you') or contains(text(), 'submitted')]")))
        print("✅ Form submission likely successful.")
    except TimeoutException:
        print("⚠️ Submission confirmation not detected. Check manually.")
    except NoSuchWindowException:
        print("⚠️ Browser window closed during confirmation check.")

# --- LINKEDIN EASY APPLY ---
# --- LINKEDIN EASY APPLY ---
def fill_application(driver, user_details):
    print("Filling LinkedIn Easy Apply form...")
    logger.info("Filling LinkedIn Easy Apply form...")
    time.sleep(3)
    filled_selectors = set()

    phone_number = user_details.get("phone", "")
    first_name   = user_details.get("first_name", "")
    last_name    = user_details.get("last_name", "")
    linkedin_email = user_details.get("email", "")
    resume_path  = user_details.get("resume", "")
    
    try:
        phone_field = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[aria-label='Phone number']"))
        )
        selector = "[aria-label='Phone number']"
        if selector not in filled_selectors:
            phone_field.clear()
            for char in phone_number:  # Simulate human typing
                phone_field.send_keys(char)
                time.sleep(0.1)
            print("Filled phone number.")
            filled_selectors.add(selector)
    except:
        print("No phone number field found.")
    
    try:
        upload_input = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        selector = "input[type='file']"
        if selector not in filled_selectors:
            upload_input.send_keys(os.path.abspath(RESUME_PATH))
            print("Uploaded resume.")
            filled_selectors.add(selector)
            time.sleep(3)
    except:
        print("No resume upload field found.")

        # 👇 One shot semantic fill for text/dropdowns inside the Easy Apply modal
    form_map = {
        "first name": first_name,
        "last name":  last_name,
        "email":      linkedin_email,
        "phone":      phone_number,
        "location":   user_details.get("location") or user_details.get("preferred_location",""),
        "education":  (user_details.get("education","") or "").split("\n")[0],
        "experience": (user_details.get("employment","") or "").split("\n")[0],
        "skills":     user_details.get("key_skills",""),
        "resume":     RESUME_PATH,
    }
    try:
        FormFiller(driver, WebDriverWait(driver, 10)).fill_all(form_map)
    except Exception as _:
        pass

    
    while True:
        time.sleep(5)
        clickable_elements = get_clickable_elements(driver)
        client = OpenAI(api_key=openai.api_key)
        index, reason = ask_llm_to_select_button(clickable_elements, client)
        if index is None:
            print("No valid button to proceed. Checking for submit...")
            if try_click_submit(driver):
                break
            print("No more steps found.")
            break
        if not click_element_by_description(driver, clickable_elements[index]):
            print("Failed to click LLM-chosen button. Checking for submit...")
            if try_click_submit(driver):
                break
        filled_selectors.clear()  # Reset after page change
        time.sleep(3)

# --- MAIN APPLICATION LOGIC ---
def process_application(user_details):
    logger.info("Enter process_application function")
    global driver
    original_window = driver.current_window_handle
    time.sleep(3)
    switch_to_new_window(original_window)

    if page_contains_signup(driver):
        if handle_signup(driver, user_details):
            print("🔓 Sign-up completed. Retrying application flow...")
            time.sleep(3)
    
    if "linkedin.com" in driver.current_url:
        fill_application(driver, user_details) 
    else:
        process_external_application(driver, user_details)

# --- RUN APPLICATION PROCESS ---
print("Automation complete. You may close the browser.")
logger.info("Automation complete. You may close the browser.")

# --- MAIN EXECUTION ---


# ===================== SAFE ENTRYPOINTS =====================

def run_linkedin_for_candidate(candidate_id, flask_app=None):
    logger.info(f"Enter run_linkedin_for_candidate function : {candidate_id}")
    global driver
    driver = get_chrome_driver()
    user_details = {}  # TODO: load user details for candidate_id
    process_application(user_details)

    if driver:
        driver.quit()
        driver = None

    """Entry point called from Flask server.py"""
    from models import Candidate, Job, db
    from flask import current_app
    from datetime import datetime

    app = flask_app or current_app._get_current_object()
    with app.app_context():
        candidate = Candidate.query.get(candidate_id)
        if not candidate:
            raise RuntimeError(f"Candidate {candidate_id} not found")

        first, *rest = (candidate.name or "").strip().split()
        last = " ".join(rest) if rest else ""
        user_details = {
            "first_name": first or "",
            "last_name": last or "",
            "email": candidate.email or "",
            "phone": candidate.phone or "",
            "location": candidate.preferred_location or (candidate.state or ""),
            "education": candidate.education or "",
            "employment": candidate.employment or "",
            "key_skills": candidate.key_skills or "",
            "resume": candidate.resume_path or "",
        }

        job = Job.query.filter_by(candidate_id=candidate_id, source="linkedin", status="queued") \
                       .order_by(Job.created_at.asc()).first()
        if not job:
            app.logger.info(f"[LinkedIn] No queued jobs for candidate {candidate_id}")
            logger.info(f"[LinkedIn] No queued jobs for candidate {candidate_id}")
            return {"status": "idle", "jobs_processed": 0}

        job_url = job.link

    try:

        with app.app_context():
            j = Job.query.filter_by(link=job_url).first()
            if j:
                j.status = "applied"
                j.comment = (j.comment or "") + "\nLinkedIn automation: success"
            db.session.commit()
    except Exception as e:
        with app.app_context():
            j = Job.query.filter_by(link=job_url).first()
            if j:
                j.status = "retry"
                j.comment = (j.comment or "") + f"\nLinkedIn automation: failed {datetime.utcnow()}"
            db.session.commit()
        raise
    finally:
        driver.quit()


def run_job_from_csv():
    """One-off local test using jobs.csv and user_details.json"""
    import csv, json

    with open("jobs.csv", newline='', encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        first_link = next(reader)[0]

    with open("user_details.json", "r", encoding="utf-8") as f:
        user_details = json.load(f)

def page_contains_signup(driver):
    logger.info("Enter page_contains_signup function")
    try:
        # Look for common sign-up fields
        signup_indicators = [
            "//input[@type='email']",
            "//input[@type='password']",
            "//input[contains(@name, 'confirm')]",
            "//button[contains(., 'Sign up') or contains(., 'Register')]",
            "//button[contains(., 'Create Account')]"
        ]
        for xpath in signup_indicators:
            if driver.find_elements(By.XPATH, xpath):
                print("Sign-up form detected.")
                logger.info("Sign-up form detected.")
                return True
        return False
    except Exception as e:
        print(f"Error checking sign-up form: {e}")
        logger.error(f"Error checking sign-up form: {e}")
        return False

def handle_signup(driver, user_details):
    logger.info("Enter handle_signup function")
    print("Handling sign-up flow...")
    signup_map = {
        "first name": user_details.get("first_name", ""),
        "last name": user_details.get("last_name", ""),
        "email": user_details.get("email", ""),
        "password": user_details.get("password", "AutoGen123!"),  # fallback if missing
        "phone": user_details.get("phone", "")
    }

    try:
        FormFiller(driver, WebDriverWait(driver, 10)).fill_all(signup_map)
        time.sleep(1)

        # Click the "Sign Up" button
        buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Sign up') or contains(., 'Register')]")
        if buttons:
            driver.execute_script("arguments[0].scrollIntoView(true);", buttons[0])
            time.sleep(1)
            buttons[0].click()
            print("Submitted sign-up form.")
            logger.info("Submitted sign-up form.")
            time.sleep(3)
            return True
        else:
            print("No visible sign-up button found.")
            logger.info("No visible sign-up button found.")
            return False
    except Exception as e:
        print(f"Sign-up failed: {e}")
        logger.error(f"Sign-up failed: {e}")
        return False


if __name__ == "__main__":
    run_job_from_csv()
