import json
import time
from openai import OpenAI
import os
from flask import Flask
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException, TimeoutException, NoSuchWindowException,
    ElementClickInterceptedException, NoSuchElementException
)
from flask_sqlalchemy import SQLAlchemy
from models import db, User, Candidate, Job


# Initialize Flask app for SQLAlchemy
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = ''
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)

class Profile(db.Model):
    __tablename__ = 'profiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    resume_path = db.Column(db.String(255))
    work_authorization = db.Column(db.String(50))
    preferred_location = db.Column(db.String(100))
    key_skills = db.Column(db.Text)
    employment = db.Column(db.Text)
    education = db.Column(db.Text)
    certifications = db.Column(db.Text)
    projects = db.Column(db.Text)

class Job(db.Model):
    __tablename__ = 'jobs'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(50), nullable=False)

# === CONFIG ===
OPENAI_API_KEY = ""
RESUME_DIR = "resumes"
MAX_RETRIES = 3
WAIT_SECONDS = 15
VISUAL_FALLBACK = True

# === VISUAL FALLBACK SETUP ===
try:
    from PIL import Image
    import pytesseract
    import cv2
    import numpy as np
    import io
    VISUAL_FALLBACK_AVAILABLE = True
except ImportError:
    VISUAL_FALLBACK_AVAILABLE = False
    if VISUAL_FALLBACK:
        print("⚠️ Visual fallback dependencies not installed. Run: pip install pillow pytesseract opencv-python")

# === INITIALIZE OPENAI ===
client = OpenAI(api_key=OPENAI_API_KEY)

# === LOAD USER DETAILS ===
with app.app_context():
    user = User.query.filter_by(email="bhaveshwalankar@gmail.com").first()
    profile = Profile.query.filter_by(user_id=user.id).first() if user else None
    user_details = {
        "first_name": user.first_name if user else "",
        "last_name": user.last_name if user else "",
        "email": user.email if user else "",
        "phone": user.phone if user else "",
        "resume_path": profile.resume_path if profile else "",
        "work_authorization": profile.work_authorization if profile else "",
        "preferred_location": profile.preferred_location if profile else "",
        "key_skills": profile.key_skills if profile else "",
        "employment": profile.employment if profile else "",
        "education": profile.education if profile else "",
        "certifications": profile.certifications if profile else "",
        "projects": profile.projects if profile else ""
    }

linkedin_email = user_details.get("email", "")
linkedin_password = user_details.get("password", "")
phone_number = user_details.get("phone", "")
if not linkedin_email or not linkedin_password:
    print("⚠️ Please ensure user email and password are available in the database.")
    exit()

# === UTILITY FUNCTIONS ===
def call_openai_api(prompt, model="gpt-4"):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ OpenAI API error: {e}")
        return ""

def get_dynamic_answer(question_text, user_profile, options=None):
    prompt = f"""
You are an intelligent job application assistant.
User profile:
{json.dumps(user_profile, indent=2)}
Question: "{question_text}"
{f"Available options: {json.dumps(options, indent=2)}" if options else ""}
Provide ONLY the most suitable value based on the user profile and question context.
For dropdowns, select an option from the provided list that best matches the profile or question intent.
Return 'N/A' if no suitable value is found.
"""
    return call_openai_api(prompt) or "N/A"

# === PLATFORM DETECTION ===
def detect_platform(driver):
    url = driver.current_url.lower()
    html = driver.page_source.lower()
    if "greenhouse" in url or "greenhouse.io" in url or "greenhouse" in html:
        return "greenhouse"
    if "myworkdayjobs.com" in url or "workday" in html:
        return "workday"
    if "lever.co" in url or "lever" in html:
        return "lever"
    if "linkedin.com" in url or "linkedin" in html:
        return "linkedin"
    return "generic"

# --- LINKEDIN LOGIN ---
def linkedin_login(driver, wait):
    print("Navigating to LinkedIn login page...")
    driver.get("https://www.linkedin.com/login")
    
    try:
        wait.until(EC.presence_of_element_located((By.ID, "username")))
        email_field = driver.find_element(By.ID, "username")
        pass_field = driver.find_element(By.ID, "password")
        email_field.send_keys(linkedin_email)
        pass_field.send_keys(linkedin_password)
        login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
        login_btn.click()
        print("Submitted login form.")
        time.sleep(3)
    except Exception as e:
        print(f"Login failed: {e}")
        driver.quit()
        exit()

# --- CLICK EASY APPLY BUTTON ---
def click_easy_apply(driver, wait):
    print("Attempting to click Easy Apply button...")
    selectors = [
        "button.jobs-apply-button",
        "button[data-control-name='apply']",
        "button.jobs-s-apply",
        "//button[contains(., 'Apply')]"
    ]
    
    for attempt in range(MAX_RETRIES):
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".jobs-details")))
            for selector in selectors:
                try:
                    button = wait.until(
                        EC.element_to_be_clickable((By.XPATH if selector.startswith("//") else By.CSS_SELECTOR, selector))
                    )
                    driver.execute_script("window.scrollTo(0, arguments[0].getBoundingClientRect().top - 200);", button)
                    time.sleep(1)
                    try:
                        driver.find_element(By.CSS_SELECTOR, "button[aria-label='Dismiss']").click()
                        time.sleep(1)
                    except:
                        pass
                    button.click()
                    print("Successfully clicked Easy Apply button.")
                    return True
                except Exception as e:
                    print(f"Attempt {attempt + 1}, selector '{selector}' failed: {str(e)[:100]}...")
            time.sleep(3)
        except Exception as e:
            print(f"Easy Apply attempt {attempt + 1} failed: {e}")
    
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button")
        for button in buttons:
            if "apply" in button.text.lower():
                driver.execute_script("arguments[0].click();", button)
                print("Used JavaScript click fallback.")
                return True
    except:
        pass
    
    print("All attempts to click Easy Apply failed.")
    return False

# === VISUAL FIELD DETECTION ===
def find_fields_visually(driver):
    if not VISUAL_FALLBACK_AVAILABLE:
        return []
    try:
        print("🖼️ Attempting visual field detection...")
        screenshot = driver.get_screenshot_as_png()
        img = Image.open(io.BytesIO(screenshot))
        img_np = np.array(img)
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        text_data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
        fields = driver.find_elements(By.XPATH, "//input | //textarea | //div[@role='textbox']")
        found_fields = []
        for i, text in enumerate(text_data['text']):
            if text.strip() and int(text_data['conf'][i]) > 60:
                x, y, w, h = text_data['left'][i], text_data['top'][i], text_data['width'][i], text_data['height'][i]
                for field in fields:
                    try:
                        field_location = field.location
                        if (abs(x - field_location['x']) < 100 and abs(y - field_location['y']) < 50):
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

# === SCRAPE FORM FIELDS ===
def scrape_form_fields(driver):
    print("🔍 Scraping form fields...")
    elements = driver.find_elements(By.XPATH, """
        //*[self::input or self::textarea or self::select or 
            @role='textbox' or @role='combobox' or @role='listbox' or
            contains(@class, 'input') or contains(@class, 'field') or
            contains(@class, 'form-control') or @data-testid='input-field']
    """)
    fields = {}
    for field in elements:
        try:
            if not field.is_displayed() or not field.is_enabled():
                continue
            field_id = field.get_attribute("id") or ""
            field_name = field.get_attribute("name") or ""
            placeholder = field.get_attribute("placeholder") or ""
            aria_label = field.get_attribute("aria-label") or ""
            testid = field.get_attribute("data-testid") or ""
            field_type = field.get_attribute("type") or ""

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

# === LLM FIELD MAPPING ===
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
    response = call_openai_api(prompt)
    try:
        return json.loads(response) if response else {}
    except json.JSONDecodeError:
        print(f"⚠️ Invalid LLM field mapping response: {response}")
        # Fallback to direct field value fetching
        mapping = {}
        for selector, field_info in scraped_fields.items():
            question_text = (
                field_info.get("aria_label") or
                field_info.get("placeholder") or
                field_info.get("name") or
                field_info.get("id") or
                field_info.get("visual_label") or
                "Unknown Field"
            )
            value = get_dynamic_answer(question_text, user_details)
            if value != "N/A":
                mapping[selector] = value
        return mapping

# === FILL FIELDS ===
def fill_fields_from_mapping(driver, mapping, user_details, filled_selectors):
    for selector, detail_key in mapping.items():
        if selector in filled_selectors:
            continue
        value = user_details.get(detail_key, "")
        if not value:
            value = get_dynamic_answer(f"What value should go in '{selector}'?", user_details)
        if not value or value == "N/A":
            continue
        try:
            if selector.startswith('visual:'):
                label = selector.replace('visual:', '')
                field = mapping[selector]['element']
            else:
                field = driver.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", field)
            time.sleep(0.3)
            if field.tag_name == "select":
                Select(field).select_by_visible_text(value)
            elif field.get_attribute("type") == "file":
                field.send_keys(os.path.abspath(os.path.join(RESUME_DIR, user_details.get("resume_path", ""))))
            elif field.get_attribute("type") in ["checkbox", "radio"] and not field.is_selected():
                field.click()
            else:
                field.clear()
                for char in str(value):
                    field.send_keys(char)
                    time.sleep(0.05)
            print(f"✅ Filled {selector} with {value}")
            filled_selectors.add(selector)
        except Exception as e:
            print(f"❌ Failed to fill {selector}: {e}")

# === FILL DYNAMIC FORM FIELDS ===
def fill_dynamic_form_fields(driver, user_details, filled_selectors, wait):
    for attempt in range(MAX_RETRIES):
        elements = driver.find_elements(By.XPATH, "//input | //textarea | //select | //div[@role='textbox' or @role='combobox' or @role='listbox']")
        unfilled_elements = []
        for elem in elements:
            if not elem.is_displayed() or not elem.is_enabled():
                continue
            try:
                field_id = elem.get_attribute("id")
                field_name = elem.get_attribute("name")
                placeholder = elem.get_attribute("placeholder")
                aria_label = elem.get_attribute("aria-label")
                testid = elem.get_attribute("data-testid") or ""
                selector = (
                    f"[data-testid='{testid}']" if testid else
                    f"#{field_id}" if field_id and ":" not in field_id and not field_id.isdigit() else
                    f"[name='{field_name}']" if field_name else
                    f"[placeholder='{placeholder}']" if placeholder else
                    f"[aria-label='{aria_label}']" if aria_label else
                    f"{elem.tag_name}[id='{field_id}']" if field_id else
                    None
                )
                if not selector or selector in filled_selectors:
                    continue
                if ":" in selector and not selector.startswith("["):
                    print(f"⚠️ Skipping invalid selector: {selector}")
                    continue

                question_text = (
                    driver.execute_script("""
                        let el = arguments[0];
                        let labelEl = el.closest('div').querySelector('label, span, .form-label, legend') || 
                                      el.closest('div').querySelector('p, h3') || 
                                      document.evaluate('./preceding-sibling::label', el, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        return labelEl ? labelEl.innerText.trim() : '';
                    """, elem) or aria_label or placeholder or field_name or field_id or "Unknown Field"
                )
                # Prioritize required fields
                is_required = bool(driver.execute_script("""
                    return arguments[0].required || 
                           arguments[0].closest('div').querySelector('span.required, span[aria-required="true"], label.required');
                """, elem))
                if is_required:
                    print(f"🔍 Detected required field: {question_text}")
                # Handle location/city fields
                if "location" in question_text.lower() or "city" in question_text.lower():
                    value = user_details.get("preferred_location", "San Francisco, CA, USA")
                    for retry in range(MAX_RETRIES):
                        try:
                            elem.clear()
                            for char in value:
                                elem.send_keys(char)
                                time.sleep(0.02)
                            options = wait.until(
                                EC.visibility_of_any_elements_located((
                                    By.XPATH, "//div[contains(@class,'option') and @role='option'] | //div[@role='option']"
                                ))
                            )
                            matched = False
                            for opt in options:
                                opt_text = opt.text.strip().lower()
                                if value.lower() in opt_text or opt_text in value.lower():
                                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); window.scrollBy(0, -200);", opt)
                                    time.sleep(0.3)
                                    try:
                                        wait.until(EC.element_to_be_clickable(opt))
                                        opt.click()
                                    except:
                                        driver.execute_script("arguments[0].click();", opt)
                                    print(f"✅ Selected location from autocomplete: {opt.text}")
                                    matched = True
                                    break
                            if not matched and options:
                                options[0].click()
                                print(f"⚠️ No exact match, selected default option: {options[0].text}")
                            filled_selectors.add(selector)
                            break
                        except StaleElementReferenceException:
                            print(f"⚠️ Stale element in location field attempt {retry + 1}, retrying...")
                            time.sleep(1)
                            elem = driver.find_element(By.CSS_SELECTOR, selector) if selector else None
                            if not elem:
                                break
                        except Exception as e:
                            print(f"⚠️ Failed to select location from dropdown menu: {e}")
                            break
                    if selector in filled_selectors:
                        continue
                # Handle standard <select> dropdowns
                if elem.tag_name == "select":
                    for retry in range(MAX_RETRIES):
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(0.2)
                            wait.until(EC.element_to_be_clickable(elem))
                            select = Select(elem)
                            options = [opt.text.strip() for opt in select.options if opt.text.strip()]
                            if not options:
                                continue
                            value = get_dynamic_answer(question_text, user_details, options)
                            if value != "N/A" and value in options:
                                select.select_by_visible_text(value)
                                print(f"✅ Selected dropdown: {question_text} -> {value}")
                                filled_selectors.add(selector)
                                break
                            else:
                                print(f"⚠️ No matching dropdown option for {question_text}: {value}")
                        except StaleElementReferenceException:
                            print(f"⚠️ Stale element in dropdown attempt {retry + 1}, retrying...")
                            time.sleep(0.5)
                            elem = driver.find_element(By.CSS_SELECTOR, selector) if selector else None
                            if not elem:
                                break
                        except Exception as e:
                            print(f"⚠️ Failed to process dropdown {question_text}: {e}")
                            break
                    if selector in filled_selectors:
                        continue
                # Handle custom dropdowns
                if elem.get_attribute("aria-haspopup") == "listbox" or elem.get_attribute("role") == "combobox":
                    for retry in range(MAX_RETRIES):
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(0.2)
                            wait.until(EC.element_to_be_clickable(elem))
                            elem.click()
                            time.sleep(0.3)
                            options = wait.until(
                                EC.visibility_of_any_elements_located((
                                    By.XPATH, "//div[contains(@class,'select__option') or @role='option'] | //li[@role='option']"
                                ))
                            )
                            value = get_dynamic_answer(question_text, user_details, [opt.text.strip() for opt in options])
                            matched = False
                            for opt in options:
                                opt_text = opt.text.strip()
                                if value.lower() in opt_text.lower():
                                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", opt)
                                    time.sleep(0.2)
                                    wait.until(EC.element_to_be_clickable(opt))
                                    opt.click()
                                    print(f"✅ Filled (custom dropdown): {question_text} -> {opt_text}")
                                    matched = True
                                    break
                            if not matched and options:
                                wait.until(EC.element_to_be_clickable(options[0]))
                                options[0].click()
                                print(f"⚠️ No match, selected default option: {options[0].text}")
                            filled_selectors.add(selector)
                            break
                        except StaleElementReferenceException:
                            print(f"⚠️ Stale element in custom dropdown attempt {retry + 1}, retrying...")
                            time.sleep(0.5)
                            elem = driver.find_element(By.CSS_SELECTOR, selector) if selector else None
                            if not elem:
                                break
                        except Exception as e:
                            print(f"⚠️ Failed to process custom dropdown {question_text}: {e}")
                            break
                    if selector in filled_selectors:
                        continue
                # Handle file uploads
                if elem.get_attribute("type") == "file":
                    elem.send_keys(os.path.abspath(os.path.join(RESUME_DIR, user_details.get("resume_path", ""))))
                    print(f"✅ Resume uploaded: {question_text}")
                    filled_selectors.add(selector)
                    continue
                # Handle Yes/No buttons
                if "yes" in question_text.lower() or "no" in question_text.lower():
                    options = ["Yes", "No"]
                    value = get_dynamic_answer(question_text, user_details, options)
                    if value in options:
                        try:
                            button = elem.find_element(By.XPATH, f".//button[contains(translate(., 'YESNO', 'yesno'), '{value.lower()}')]")
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                            wait.until(EC.element_to_be_clickable(button))
                            button.click()
                            print(f"✅ Clicked '{value}' for: {question_text}")
                            filled_selectors.add(selector)
                            continue
                        except:
                            print(f"⚠️ No matching Yes/No button for: {question_text}")
                # Handle regular input/textarea
                value = get_dynamic_answer(question_text, user_details)
                if value == "N/A":
                    continue
                if elem.get_attribute("type") == "email" and "@" not in value:
                    continue
                for retry in range(MAX_RETRIES):
                    try:
                        elem.clear()
                        for char in value:
                            elem.send_keys(char)
                            time.sleep(0.02)
                        print(f"✅ Filled: {question_text} -> {value}")
                        filled_selectors.add(selector)
                        break
                    except StaleElementReferenceException:
                        print(f"⚠️ Stale element in input attempt {retry + 1}, retrying...")
                        time.sleep(0.5)
                        elem = driver.find_element(By.CSS_SELECTOR, selector) if selector else None
                        if not elem:
                            break
                    except Exception as e:
                        print(f"⚠️ Failed to fill {question_text}: {e}")
                        break
                if selector not in filled_selectors:
                    unfilled_elements.append(question_text)
            except StaleElementReferenceException:
                print(f"⚠️ Stale element for {question_text}. Will retry in next iteration.")
                unfilled_elements.append(question_text)
            except Exception as e:
                print(f"⚠️ Failed to process {question_text}: {e}")
                unfilled_elements.append(question_text)
        if not unfilled_elements:
            print("✅ All fields filled successfully.")
            break
        print(f"⚠️ {len(unfilled_elements)} fields remain unfilled: {unfilled_elements}. Retrying...")
        time.sleep(1)
    return len(unfilled_elements) == 0

# === SCRAPE CLICKABLE ELEMENTS ===
def get_clickable_elements(driver):
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
                    score = 10 if elem.is_displayed() and elem.is_enabled() else 0
                    score += 8 if section_name == "application-form" else 0
                    score += 5 if near_input else 0
                    score -= 5 if section_name in ["header", "footer"] else 0
                    score += 3 if section_name == "modal" else 0
                    score += 2 if elem.get_attribute("tabindex") and int(elem.get_attribute("tabindex")) >= 0 else 0
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
            print(f"⚠️ Error scraping section {section_name}: {e}")
    elements.sort(key=lambda x: x["score"], reverse=True)
    return elements

# === LLM BUTTON SELECTION ===
def ask_llm_to_select_button(elements):
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
        response = json.loads(call_openai_api(prompt))
        index = response.get("index")
        reason = response.get("reason", "No reason provided")
        if index < 0 or index >= len(elements):
            return None, None
        return index, reason
    except Exception as e:
        print(f"⚠️ LLM button selection failed: {e}")
        return None, None

# === CLICK ELEMENT WITH RETRY ===
def click_element_by_description(driver, element_description):
    for attempt in range(MAX_RETRIES):
        try:
            elem = element_description["element"]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            time.sleep(0.5)
            elem.click()
            print(f"✅ Clicked: {element_description['button_text']} (Section: {element_description['section']})")
            WebDriverWait(driver, 5).until(EC.staleness_of(elem) or EC.presence_of_element_located((By.CSS_SELECTOR, "div")))
            return True
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed to click element: {e}")
            time.sleep(1)
    return False

def fill_application(driver, wait):
    print("Filling LinkedIn Easy Apply form...")
    time.sleep(3)
    filled_selectors = set()
    
    try:
        phone_field = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[aria-label='Phone number']"))
        )
        selector = "[aria-label='Phone number']"
        if selector not in filled_selectors:
            phone_field.clear()
            for char in phone_number:
                phone_field.send_keys(char)
                time.sleep(0.1)
            print("Filled phone number.")
            filled_selectors.add(selector)
    except:
        print("No phone number field found.")
    
    try:
        upload_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        selector = "input[type='file']"
        if selector not in filled_selectors:
            upload_input.send_keys(os.path.abspath(os.path.join(RESUME_DIR, user_details.get("resume_path", ""))))
            print("Uploaded resume.")
            filled_selectors.add(selector)
            time.sleep(3)
        else:
            print("Resume already uploaded, skipping.")
    except:
        print("No resume upload field found.")
    
    while True:
        clickable_elements = get_clickable_elements(driver)
        client = OpenAI(api_key=OPENAI_API_KEY)
        index, reason = ask_llm_to_select_button(clickable_elements)
        if index is None:
            print("No valid button to proceed. Checking for submit...")
            if try_click_submit(driver, wait):
                break
            print("No more steps found.")
            break
        if not click_element_by_description(driver, clickable_elements[index]):
            print("Failed to click LLM-chosen button. Checking for submit...")
            if try_click_submit(driver, wait):
                break
        filled_selectors.clear()
        time.sleep(3)

# === TRY CLICK SUBMIT ===
def try_click_submit(driver, wait):
    try:
        submit_btn = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[contains(text(), 'Submit') or contains(text(), 'Apply')]")
        ))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
        time.sleep(0.5)
        driver.execute_script("window.scrollBy(0, -150);")
        try:
            submit_btn.click()
            print("✅ Submit button clicked.")
        except Exception as e:
            print(f"⚠️ Normal click failed: {e}. Trying JS fallback...")
            driver.execute_script("arguments[0].click();", submit_btn)
            print("✅ Submit button clicked via JS.")
        return True
    except Exception as e:
        print(f"❌ Submit button not found or not clickable: {e}")
        return False

# --- HANDLE WINDOW/TAB SWITCHING ---
def switch_to_new_window(driver, original_window):
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

# === PROCESS APPLICATION ===
def process_application(driver, wait, job_url, user_details):
    print(f"\n=== Processing job: {job_url} ===")
    driver.get(job_url)
    time.sleep(3)
    platform = detect_platform(driver)
    print(f"🧠 Platform detected: {platform.capitalize()}")
    filled_selectors = set()
    original_window = driver.current_window_handle
    switch_to_new_window(driver, original_window)

    if "linkedin.com" in driver.current_url:
        print("On LinkedIn Easy Apply form.")
        if not click_easy_apply(driver, wait):
            print("⚠️ Failed to click Easy Apply. Proceeding with form filling.")
        switch_to_new_window(driver, original_window)
        fill_application(driver, wait)
    else:
        print(f"Redirected to external site: {driver.current_url}")

    for step in range(5):
        try:
            if not driver.window_handles:
                print("⚠️ Browser window closed unexpectedly.")
                return
            if driver.current_window_handle != original_window:
                driver.switch_to.window(driver.window_handles[-1])
                print(f"✅ Switched to new window: {driver.current_url}")
            if page_contains_form(driver):
                fields = scrape_form_fields(driver)
                if fields:
                    for retry in range(MAX_RETRIES):
                        try:
                            mapping = ask_llm_to_match_fields(fields, user_details)
                            print("🔁 LLM Field Mapping:")
                            print(json.dumps(mapping, indent=2))
                            fill_fields_from_mapping(driver, mapping, user_details, filled_selectors)
                            break
                        except Exception as e:
                            print(f"⚠️ LLM mapping retry {retry + 1} failed: {e}")
                            time.sleep(1)
                if not fill_dynamic_form_fields(driver, user_details, filled_selectors, wait):
                    print("⚠️ Some fields could not be filled. Attempting to proceed...")
            for retry in range(MAX_RETRIES):
                if try_click_submit(driver, wait):
                    print("✅ Submission attempted successfully.")
                    break
                print(f"⚠️ Submit attempt {retry + 1} failed. Retrying...")
                time.sleep(2)
            else:
                clickable_elements = get_clickable_elements(driver)
                if clickable_elements:
                    index, reason = ask_llm_to_select_button(clickable_elements)
                    if index is not None and click_element_by_description(driver, clickable_elements[index]):
                        print(f"✅ Clicked navigation button: {reason}")
                        filled_selectors.clear()
                        time.sleep(3)
                        switch_to_new_window(driver, original_window)
                        continue
            for retry in range(MAX_RETRIES):
                if try_click_submit(driver, wait):
                    print("✅ Submission attempted successfully.")
                    break
                print(f"⚠️ Submit attempt {retry + 1} failed. Retrying...")
                time.sleep(2)
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Thank you') or contains(text(), 'submitted')]"))
                )
                print("✅ Form submission likely successful.")
                break
            except TimeoutException:
                print("⚠️ Submission confirmation not detected. Check manually.")
                break
        except NoSuchWindowException:
            print("⚠️ Browser window closed unexpectedly.")
            return
        except Exception as e:
            print(f"⚠️ Error in application step {step + 1}: {e}")
            time.sleep(2)
    if step == 4:
        print("⚠️ Reached maximum steps without submission confirmation. Check manually.")

# === DETECT FORM PRESENCE ===
def page_contains_form(driver):
    try:
        form_elements = driver.find_elements(By.XPATH, ".//li | .//div[@role='option'] | .//div[contains(@class, 'option') or contains(@class,'select__option')]")
        return len(form_elements) > 0
    except Exception:
        return False

# === MAIN ENTRY ===
def main(candidate_id=None):
    global driver
    options = Options()
    options.add_experimental_option("detach", True)
    options.add_argument("--start-maximized")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = webdriver.Chrome(options=options)

    wait = WebDriverWait(driver, WAIT_SECONDS)

    linkedin_login(driver, wait)
    time.sleep(3)

    with app.app_context():
        if not candidate_id:
            print("❌ Candidate ID is required.")
            return

        # Fetch jobs for this candidate
        jobs = Job.query.filter_by(candidate_id=candidate_id).all()
        job_urls = [job.link for job in jobs if job.link and job.link.startswith("http")]

        # Load recruiter user and candidate profile
        user = db.session.query(User).join(Candidate, Candidate.recruiter_id == User.id)\
            .filter(Candidate.id == candidate_id).first()
        profile = Candidate.query.get(candidate_id)

        if not user or not profile:
            print("❌ No user or profile found for candidate_id:", candidate_id)
            return

        # Fill user details from DB
        user_details.update({
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "resume_path": profile.resume_path,
            "work_authorization": profile.work_authorization,
            "preferred_location": profile.preferred_location,
            "key_skills": profile.key_skills,
            "employment": profile.employment,
            "education": profile.education,
            "certifications": profile.certifications,
            "projects": profile.projects,
        })

    if not job_urls:
        print("⚠️ No job URLs found in database.")
        driver.quit()
        return

    print(f"🚀 Loaded {len(job_urls)} job URLs.")
    for job_url in job_urls:
        process_application(driver, wait, job_url, user_details)

    print("\n✅ All jobs processed. Please verify applications manually!")
    driver.quit()


if __name__ == "__main__":
    main()