import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
import openai

# === CONFIG ===
OPENAI_API_KEY = ""
JOB_URL = "https://job-boards.greenhouse.io/discord/jobs/8035019002?gh_src=5117e0c52us"
USER_DETAILS_FILE = "user_details.json"
MAX_RETRIES = 3

# === LOAD USER DETAILS ===
with open(USER_DETAILS_FILE, "r", encoding="utf-8") as f:
    user_details = json.load(f)

openai.api_key = OPENAI_API_KEY
RESUME_PATH = user_details.get("resume_path", "")

# === LLM FIELD VALUE FUNCTION ===
def ask_llm_field_value(question_text):
    prompt = f"""
    A user is applying for a job. Based on the following question or field label, what should they answer?
    Question: "{question_text}"
    User details: {json.dumps(user_details)}
    Respond with only the exact value to enter or say N/A.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ OpenAI API error for '{question_text}': {e}")
        return "N/A"

# === FIELD FILLING FUNCTION ===
def fill_field(driver, field, wait):
    question_text = (
        field.get_attribute("aria-label") or
        field.get_attribute("placeholder") or
        field.get_attribute("name") or
        field.get_attribute("id") or
        ""
    )
    tag = field.tag_name
    field_type = field.get_attribute("type") or ""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", field)
        time.sleep(0.2)

        # LOCATION / CITY AUTOCOMPLETE PRIORITY
        if ("location" in question_text.lower() or "city" in question_text.lower()):
            value = ask_llm_field_value(question_text)
            field.clear()
            for char in value:
                field.send_keys(char)
                time.sleep(0.05)

            # Wait for suggestions to appear
            try:
                # Wait up to 6 secs for at least one option to be visible
                options = wait.until(
                    EC.visibility_of_any_elements_located((
                        By.XPATH, "//div[contains(@class,'option') and @role='option'] | //div[@role='option']"
                    ))
                )
                matched = False
                for opt in options:
                    opt_text = opt.text.strip().lower()
                    if value.lower() in opt_text or opt_text in value.lower():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", opt)
                        time.sleep(0.2)
                        opt.click()
                        print(f"✅ Location selected from menu: {opt.text}")
                        matched = True
                        break
                if not matched and options:
                    options[0].click()
                    print(f"⚠️ No exact match, selected default option: {options[0].text}")
            except Exception as e:
                print(f"⚠️ Failed to select location from dropdown menu: {e}")

        # Standard <select> dropdown
        elif tag == "select":
            value = ask_llm_field_value(question_text)
            from selenium.webdriver.support.ui import Select
            select = Select(field)
            matched = False
            for option in select.options:
                if value.lower() in option.text.lower():
                    select.select_by_visible_text(option.text)
                    matched = True
                    break
            if not matched and len(select.options) > 1:
                select.select_by_index(1)
            print(f"✅ Filled (dropdown): {question_text}")

        # File upload
        elif field_type == "file":
            if RESUME_PATH:
                field.send_keys(RESUME_PATH)
                print(f"✅ Uploaded file: {question_text}")

        # Custom Greenhouse-style dropdown (after location logic)
        elif field.get_attribute("aria-haspopup") == "listbox" or (field.get_attribute("role") == "combobox"):
            value = ask_llm_field_value(question_text)
            field.click()
            time.sleep(0.5)
            options = driver.find_elements(By.CSS_SELECTOR, "div[class*='option'], div[role='option']")
            matched = False
            for option in options:
                if value.lower() in option.text.lower():
                    option.click()
                    matched = True
                    break
            if not matched and options:
                options[0].click()
            print(f"✅ Filled (custom dropdown): {question_text}")

        # Checkbox/radio
        elif field_type in ["checkbox", "radio"]:
            if field.is_enabled() and not field.is_selected():
                field.click()
                print(f"✅ Checked: {question_text}")

        # Standard input, textarea, etc.
        else:
            value = ask_llm_field_value(question_text)
            field.clear()
            for char in value:
                field.send_keys(char)
                time.sleep(0.02)
            print(f"✅ Filled: {question_text}")

    except Exception as e:
        print(f"❌ Failed to fill field: {question_text} | {e}")

# === MAIN SCRIPT ===
def main():
    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    try:
        driver.get(JOB_URL)
        time.sleep(4)

        # Click "Apply for this job" if present
        try:
            apply_button = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Apply for this job")))
            apply_button.click()
            time.sleep(2)
        except Exception:
            pass  # Already on form

        filled_names = set()
        while True:
            fields = driver.find_elements(By.CSS_SELECTOR, "input, textarea, select")
            # Only fill visible, enabled, and not-yet-filled fields
            to_fill = [
                f for f in fields
                if (f.get_attribute("name") or f.get_attribute("id")) not in filled_names
                and f.is_displayed() and f.is_enabled()
            ]
            if not to_fill:
                break

            for field in to_fill:
                name_or_id = field.get_attribute("name") or field.get_attribute("id") or ""
                for attempt in range(MAX_RETRIES):
                    try:
                        fill_field(driver, field, wait)
                        filled_names.add(name_or_id)
                        break  # Success
                    except StaleElementReferenceException:
                        print(f"⚠️ Stale element for field '{name_or_id}', retrying ({attempt+1}/{MAX_RETRIES})...")
                        time.sleep(0.4)
                        # Re-fetch the field reference
                        fields_now = driver.find_elements(By.CSS_SELECTOR, "input, textarea, select")
                        field = next(
                            (f for f in fields_now if (f.get_attribute("name") or f.get_attribute("id")) == name_or_id),
                            None
                        )
                        if field is None:
                            print(f"❌ Field '{name_or_id}' disappeared, skipping.")
                            break

        print("\n🎯 Autofill complete. Please verify manually before submission.")

        # Robust submit button handling
        try:
            submit_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(),'Submit') or contains(text(),'Apply')]")
            ))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", submit_button)
            time.sleep(1)
            try:
                submit_button.click()
                print("✅ Submit button clicked.")
            except Exception as e:
                print(f"⚠️ Click intercepted, trying JS fallback: {e}")
                driver.execute_script("arguments[0].click();", submit_button)
                print("✅ Submit button clicked via JS fallback.")
        except Exception as e:
            print(f"❌ Failed to click submit button: {e}")

    except Exception as e:
        print(f"❌ Error during automation: {e}")
    finally:
        input("\nPress Enter to close browser...")
        driver.quit()

if __name__ == "__main__":
    main()
