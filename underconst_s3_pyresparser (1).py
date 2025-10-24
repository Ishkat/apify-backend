from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import os
import boto3
import uuid
import io
from pyresparser import ResumeParser

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///job_platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# AWS S3 Configuration
S3_BUCKET = ''       # 🔁 Replace with your bucket name
S3_REGION = ''             # 🔁 Replace with your region
s3_client = boto3.client('s3', region_name=S3_REGION)

# Database model
class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    resume_path = db.Column(db.String(255))
    key_skills = db.Column(db.Text)
    education = db.Column(db.Text)
    employment = db.Column(db.Text)
    certifications = db.Column(db.Text)
    projects = db.Column(db.Text)

# Resume parser using pyresparser
def parse_resume(resume_path):
    try:
        if resume_path.startswith("s3://"):
            s3_key = resume_path.replace(f"s3://{S3_BUCKET}/", "")
            s3_object = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
            file_stream = io.BytesIO(s3_object['Body'].read())

            # Save to temporary file
            temp_filename = f"/tmp/{uuid.uuid4().hex}.pdf"
            with open(temp_filename, 'wb') as f:
                f.write(file_stream.read())

            data = ResumeParser(temp_filename).get_extracted_data()
            os.remove(temp_filename)
        else:
            data = ResumeParser(resume_path).get_extracted_data()

        return data or {}
    except Exception as e:
        print(f"[Resume Parse Error] {e}")
        return {}

# Upload and create candidate
@app.route('/add-candidate', methods=['POST'])
def add_candidate():
    name = request.form.get('name')
    email = request.form.get('email')
    resume = request.files.get('resume')

    if not all([name, email, resume]):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    unique_suffix = uuid.uuid4().hex[:6]
    filename = f"{name}_{email.split('@')[0]}_{unique_suffix}.pdf"
    s3_key = f"resumes/{filename}"

    try:
        s3_client.upload_fileobj(resume, S3_BUCKET, s3_key)
        resume_path = f"s3://{S3_BUCKET}/{s3_key}"
    except Exception as e:
        return jsonify({'success': False, 'message': f'Upload failed: {e}'}), 500

    candidate = Candidate(name=name, email=email, resume_path=resume_path)
    db.session.add(candidate)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Candidate added', 'candidate_id': candidate.id})

# Auto-fill resume fields from parsed data
@app.route('/autofill-resume/<int:candidate_id>', methods=['POST'])
def autofill_resume(candidate_id):
    candidate = Candidate.query.get(candidate_id)
    if not candidate or not candidate.resume_path:
        return jsonify({'success': False, 'message': 'Candidate not found'}), 404

    data = parse_resume(candidate.resume_path)
    if not data:
        return jsonify({'success': False, 'message': 'Parsing failed'}), 500

    candidate.name = data.get('name') or candidate.name
    candidate.email = data.get('email') or candidate.email
    candidate.key_skills = ", ".join(data.get('skills', [])) if data.get('skills') else None
    candidate.education = "\n".join(data.get('education', [])) if data.get('education') else None
    candidate.employment = "\n".join(data.get('experience', [])) if data.get('experience') else None
    candidate.certifications = ", ".join(data.get('certifications', [])) if data.get('certifications') else None
    candidate.projects = "\n".join(data.get('projects', [])) if data.get('projects') else None

    db.session.commit()

    return jsonify({'success': True, 'data': data})

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)
