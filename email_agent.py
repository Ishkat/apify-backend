import os
import re
import base64
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
import openai
from cryptography.fernet import Fernet

# === DB Setup (Aiven production) ===
DB_URI = (
    ""
    ""
)
engine = create_engine(DB_URI)
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()

# === Encryption Setup ===
# Hardcoded Fernet key (keep this private & secure)
FERNET_KEY = b""
fernet = Fernet(FERNET_KEY)

# === Models (redefine needed fields) ===
from sqlalchemy import Column, Integer, String, Text

class Candidate(Base):
    __tablename__ = 'candidates'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(100))
    oauth_token = Column(Text)
    refresh_token = Column(Text)
    token_uri = Column(Text)
    client_id = Column(Text)
    client_secret = Column(Text)
    scopes = Column(Text)

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    company = Column(String(255))
    candidate_id = Column(Integer)
    status = Column(String(50), default="Applied")
    interview_status = Column(String(100))
    final_verdict = Column(String(100))

# === Keyword Rules ===
rejection_keywords = [
    "not selected", "unsuccessful", "did not proceed", "not shortlisted",
    "disqualified", "not approved"
]

review_keywords = [
    "shortlisting", "evaluation", "initial review", "preliminary check",
    "pre-assessment", "qualification round", "technical review", "technical round",
    "screening session", "talent review", "discovery session"
]

# === Gmail Helper ===
def get_gmail_service(candidate_id):
    candidate = session.get(Candidate, candidate_id)
    if not candidate or not candidate.oauth_token:
        raise Exception(f"No valid credentials for candidate ID {candidate_id}")

    creds = Credentials(
        token=fernet.decrypt(candidate.oauth_token.encode()).decode(),
        refresh_token=fernet.decrypt(candidate.refresh_token.encode()).decode(),
        token_uri=candidate.token_uri,
        client_id=candidate.client_id,
        client_secret=candidate.client_secret,
        scopes=candidate.scopes.split(',')
    )
    return build('gmail', 'v1', credentials=creds)

# === OpenAI Classification ===
def classify_email_with_openai(content):
    openai.api_key = ""  # Replace with your actual OpenAI key

    prompt = f"""
Read the email below and classify it into one of the following job statuses:
- Interview Scheduled
- Offered
- Rejected
- Under Review
- No Action

Email Content:
\"\"\"
{content}
\"\"\"
Respond with just the status.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an assistant that classifies job application emails."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=20
        )
        return response.choices[0].message['content'].strip()
    except Exception as e:
        print("OpenAI API error:", e)
        return None

# === Decode email content ===
def extract_email_body(payload):
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType")
            data = part.get("body", {}).get("data")
            if data:
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                if mime_type == "text/plain":
                    return decoded
                elif mime_type == "text/html" and not body:
                    body = BeautifulSoup(decoded, "html.parser").get_text()
    elif "body" in payload:
        data = payload["body"].get("data")
        if data:
            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return body

# === Match job to email ===
def is_relevant(job, email_text):
    email_text = email_text.lower()
    title_parts = job.title.lower().split()
    company_parts = job.company.lower().split() if job.company else []

    match_title = any(word in email_text for word in title_parts if len(word) > 3)
    match_company = any(word in email_text for word in company_parts if len(word) > 3)

    return match_title or match_company

# === Agent Main Logic ===
def run_email_agent():
    candidates = session.query(Candidate).all()

    for candidate in candidates:
        try:
            service = get_gmail_service(candidate.id)
        except Exception as e:
            print(f"[SKIP] {candidate.name}: {e}")
            continue

        print(f"📨 Checking Gmail for: {candidate.name}")
        jobs = session.query(Job).filter_by(candidate_id=candidate.id).all()
        query = f"after:{(datetime.utcnow() - timedelta(days=30)).strftime('%Y/%m/%d')}"
        messages = service.users().messages().list(userId='me', q=query).execute().get('messages', [])

        for m in messages:
            msg = service.users().messages().get(userId='me', id=m['id'], format='full').execute()
            snippet = msg.get('snippet', '')
            body = extract_email_body(msg.get("payload", {}))
            content = snippet + "\n" + body

            for job in jobs:
                if is_relevant(job, content):
                    matched = False
                    content_lower = content.lower()

                    if any(kw in content_lower for kw in ["interview"] + review_keywords):
                        job.status = "Selected"
                        job.interview_status = "Interview 1"
                        job.final_verdict = "🤔 Still Thinking"
                        matched = True
                    elif "offer" in content_lower:
                        job.status = "Selected"
                        job.final_verdict = "🙌 Welcome Aboard"
                        matched = True
                    elif any(kw in content_lower for kw in ["reject", "unfortunately"] + rejection_keywords):
                        job.status = "Rejected"
                        job.final_verdict = "💔 Not a Fit"
                        matched = True

                    if not matched:
                        status = classify_email_with_openai(content)
                        if status == "Interview Scheduled":
                            job.status = "Selected"
                            job.interview_status = "Interview 1"
                            job.final_verdict = "🤔 Still Thinking"
                        elif status == "Offered":
                            job.status = "Selected"
                            job.final_verdict = "🙌 Welcome Aboard"
                        elif status == "Rejected":
                            job.status = "Rejected"
                            job.final_verdict = "💔 Not a Fit"
                        elif status == "Under Review":
                            job.status = "Applied"
                        elif status == "No Action":
                            continue

                    session.commit()
                    print(f"✔️ Updated job: {job.title}")

if __name__ == '__main__':
    run_email_agent()