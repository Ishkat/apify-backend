# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Text, Index


db = SQLAlchemy()  # ✅ Initialize SQLAlchemy here

class Company(db.Model):
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    recruiters = db.relationship('User', backref='company', lazy='dynamic')

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # ✅ <-- Add this
    is_approved = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    candidates = db.relationship('Candidate', backref='recruiter', lazy='dynamic')

class Candidate(db.Model):
    __tablename__ = 'candidates'
    id = db.Column(db.Integer, primary_key=True)
    recruiter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    profile_image = db.Column(db.String(255))  # e.g., 'uploads/bhavesh.png'
    resume_path = db.Column(db.String(255))
    key_skills = db.Column(db.Text)
    preferred_location = db.Column(db.String(100))
    work_authorization = db.Column(db.String(100))
    employment_type = db.Column(db.String(20))  # ✅ Added now
    job_type = db.Column(db.String(50))                # Full-time / Contract / etc.
    salary_expectations = db.Column(db.String(50))
    state = db.Column(db.String(100))                  # Selected US state
    remote_only = db.Column(db.Boolean, default=False) # toggle
    remote_only = db.Column(db.Boolean, default=False) # toggle
    employment = db.Column(db.Text)
    education = db.Column(db.Text)
    certifications = db.Column(db.Text)
    projects = db.Column(db.Text)
    title = db.Column(db.String(100))  # ✅ Add this
    phone = db.Column(db.String(20))   # ✅ Add this
    password = db.Column(db.String(255))  # ✅ ADD THIS LINE
    jobs = db.relationship('Job', backref='candidate', lazy='dynamic')

    oauth_token = db.Column(Text, nullable=True)
    refresh_token = db.Column(Text, nullable=True)
    token_uri = db.Column(Text, nullable=True)
    client_id = db.Column(Text, nullable=True)
    client_secret = db.Column(Text, nullable=True)
    scopes = db.Column(Text, nullable=True)
    
    job_jarvis_active = db.Column(db.Boolean, default=False)


class Job(db.Model):
    __tablename__ = 'jobs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidates.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Applied')
    comment = db.Column(db.Text, default='')
    interview_status = db.Column(db.String(100), default='')
    final_verdict = db.Column(db.String(100), default='')

# Example of composite indexes (for frequent multi-column filters)
__table_args__ = (
    Index('idx_job_user_status', 'user_id', 'status'),
    Index('idx_job_candidate_status', 'candidate_id', 'status'),
    Index('idx_job_company_location', 'company', 'location')
)






