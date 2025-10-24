
from flask import Flask, request, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import boto3
import uuid
import pdfplumber
import io

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///job_platform.db'  # Replace with your DB
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# AWS S3 Configuration
S3_BUCKET = ''  # Replace with your S3 bucket
S3_REGION = ''        # Replace with your AWS region
s3_client = boto3.client('s3', region_name=S3_REGION)

# Models (simplified for brevity)
class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    resume_path = db.Column(db.String(255))

# Resume parser
def parse_resume(resume_path):
    extracted_text = ""
    try:
        if resume_path.startswith("s3://"):
            s3_key = resume_path.replace(f"s3://{S3_BUCKET}/", "")
            s3_object = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
            file_stream = io.BytesIO(s3_object['Body'].read())
            with pdfplumber.open(file_stream) as pdf:
                for page in pdf.pages:
                    extracted_text += page.extract_text() + "\n"
        else:
            with pdfplumber.open(resume_path) as pdf:
                for page in pdf.pages:
                    extracted_text += page.extract_text() + "\n"
    except Exception as e:
        print(f"Error reading resume: {e}")
    return extracted_text

# Route to add candidate
@app.route('/add-candidate', methods=['POST'])
def add_candidate():
    name = request.form.get('name')
    email = request.form.get('email')
    resume = request.files.get('resume')

    if not all([name, email, resume]):
        return jsonify({'success': False, 'message': 'Missing fields'}), 400

    unique_suffix = uuid.uuid4().hex[:6]
    filename = f"{name}_{email.split('@')[0]}_{unique_suffix}.pdf"
    s3_key = f"resumes/{filename}"

    # Upload resume to S3
    try:
        s3_client.upload_fileobj(resume, S3_BUCKET, s3_key)
        resume_path = f"s3://{S3_BUCKET}/{s3_key}"
    except Exception as e:
        return jsonify({'success': False, 'message': f'Upload failed: {e}'}), 500

    candidate = Candidate(name=name, email=email, resume_path=resume_path)
    db.session.add(candidate)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Candidate added successfully', 'resume_path': resume_path})

# Route to get resume content
@app.route('/parse-resume/<int:candidate_id>', methods=['GET'])
def get_resume(candidate_id):
    candidate = Candidate.query.get(candidate_id)
    if not candidate or not candidate.resume_path:
        return jsonify({'success': False, 'message': 'Candidate or resume not found'}), 404

    text = parse_resume(candidate.resume_path)
    return jsonify({'success': True, 'content': text})

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)
