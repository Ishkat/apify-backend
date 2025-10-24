import os
import json
import openai
import pdfplumber

# Set your OpenAI API Key
openai.api_key = os.getenv("OPENAI_API_KEY")  # Or hardcode if needed (not recommended)

# Define paths
RESUME_FOLDER = "resumes"  # Folder where uploaded resumes are saved
JSON_FILE = "user_details_updated.json"  # File to be updated

def extract_text_from_resume(file_path):
    """Extract text from a PDF resume using pdfplumber."""
    extracted_text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                extracted_text += page.extract_text() + "\n"
        return extracted_text.strip()
    except Exception as e:
        print(f"❌ Failed to extract resume text: {e}")
        return ""

def get_updated_json_from_openai(resume_text, current_json):
    """Ask OpenAI to update the JSON values using resume text."""
    prompt = f"""
You are a smart assistant. Below is a resume and a user profile in JSON format.

Update only the *values* in the JSON based on the resume. Do not change the keys or structure. 
If a value is not found in the resume, keep the current value.

Resume:
\"\"\"
{resume_text}
\"\"\"

Current Profile JSON:
{json.dumps(current_json, indent=2)}

Return the updated JSON only.
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for parsing resumes and editing structured JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        updated_json_str = response.choices[0].message.content.strip()
        return json.loads(updated_json_str)
    except Exception as e:
        print(f"❌ Error from OpenAI: {e}")
        return current_json  # Fallback

def main():
    # Step 1: Get the latest resume file
    resume_files = sorted(
        [f for f in os.listdir(RESUME_FOLDER) if f.lower().endswith(('.pdf', '.docx'))],
        key=lambda x: os.path.getmtime(os.path.join(RESUME_FOLDER, x)),
        reverse=True
    )

    if not resume_files:
        print("❌ No resumes found in the 'resumes' folder.")
        return

    latest_resume = resume_files[0]
    resume_path = os.path.join(RESUME_FOLDER, latest_resume)
    print(f"📄 Latest resume: {latest_resume}")

    # Step 2: Extract text from resume
    resume_text = extract_text_from_resume(resume_path)
    if not resume_text:
        print("❌ Resume text is empty. Aborting.")
        return

    # Step 3: Load current JSON
    if not os.path.exists(JSON_FILE):
        print("❌ JSON file not found.")
        return
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        current_json = json.load(f)

    # Step 4: Update JSON via OpenAI
    updated_json = get_updated_json_from_openai(resume_text, current_json)

    # Step 5: Save updated JSON
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_json, f, indent=2)
    print("✅ user_details_updated.json has been updated.")

if __name__ == "__main__":
    main()
