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
RESUME_PATH = "resume.pdf"
USER_JSON = "user_details.json"
JOBS_CSV = "jobs.csv"
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
    prompt = f"""
You are an intelligent job application assistant.
Here is the user's profile:
{json.dumps(user_profile, indent=2)}
Question: "{question_text}"
{f"Available options: {json.dumps(options, indent=2)}" if options else ""}
Please provide ONLY the most suitable value for this question based on the user profile and context.
For dropdowns, select an option from the provided list that best matches the profile or question intent.
Return 'N/A' if no suitable value is found.
"""
    return call_openai_api(prompt) or "N/A"

def find_fields_visually(driver):
    """Fallback method using visual text recognition"""
    if not VISUAL_FALLBACK_AVAILABLE:
        return []
    
    try:
        from PIL import Image
        import pytesseract
        import io
        import cv2
        import numpy as np
        
        print("🖼️ Attempting visual field detection...")
        
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
driver = webdriver.Chrome()
driver.maximize_window()

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

# # --- NAVIGATE TO JOB LINK ---
target = normalize_linkedin_url(first_link)
print(f"Opening job link (normalized): {target}")
driver.get(target)


# --- CLICK EASY APPLY BUTTON ---
def click_easy_apply():
    print("Attempting to click Easy Apply button...")
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
                    button = WebDriverWait(driver, 10).until(
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
    for attempt in range(MAX_RETRIES):
        try:
            elem = element_description["element"]
            driver.execute_script("arguments[0].scrollIntoView(true);", elem)
            time.sleep(1)
            elem.click()
            print(f"Clicked element: {element_description['button_text']} (Section: {element_description['section']})")
            WebDriverWait(driver, 5).until(EC.staleness_of(elem) or EC.presence_of_element_located((By.CSS_SELECTOR, "div")))
            return True
        except Exception as e:
            print(f"Attempt {attempt + 1} failed to click element: {e}")
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
                return False
    return False

# --- SCRAPE FORM FIELDS ---
def scrape_form_fields(driver):
    print("🔍 Scraping all input/textarea/select elements on page...")
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
    try:
        form_elements = driver.find_elements(By.XPATH, "//input | //textarea | //select | //div[@role='listbox']")
        return len(form_elements) > 0
    except Exception as e:
        print(f"Error checking for form: {e}")
        return False

# --- FILL DYNAMIC FORM FIELDS ---
# --- FILL DYNAMIC FORM FIELDS ---
def fill_dynamic_form_fields(driver, user_details, filled_selectors):
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
    for attempt in range(MAX_RETRIES):
        try:
            print("🔘 Looking for Submit button...")
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
def fill_application():
    print("Filling LinkedIn Easy Apply form...")
    time.sleep(3)
    filled_selectors = set()
    
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
    
    while True:
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
def process_application(driver, user_details):
    original_window = driver.current_window_handle
    time.sleep(3)
    switch_to_new_window(original_window)
    
    if "linkedin.com" in driver.current_url:
        print("On LinkedIn Easy Apply form.")
        fill_application()
    else:
        print(f"Redirected to external site: {driver.current_url}")
        process_external_application(driver, user_details)

# --- RUN APPLICATION PROCESS ---
process_application(driver, user_details)
print("Automation complete. You may close the browser.")
driver.quit()


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Load user details
    try:
        with open(USER_JSON, 'r', encoding='utf-8') as f:
            user_details = json.load(f)
    except Exception as e:
        print(f"Failed to load user details: {e}")
        exit()

    # Initialize browser
    driver = webdriver.Chrome()
    driver.maximize_window()

    try:
        # Run application process
        process_application(driver, user_details)
    except Exception as e:
        print(f"⚠️ Critical error: {e}")
    finally:
        driver.quit()
        print("Automation complete.")