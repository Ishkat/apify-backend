# Use lightweight Python image
FROM python:3.11-slim

# Install system dependencies required by blis, numpy, spacy, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ python3-dev \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Upgrade pip, setuptools, wheel before installing dependencies
RUN pip install --upgrade pip setuptools wheel

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .

# Install dependencies (avoid cache bloat)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app (including /templates)
COPY . .

# ✅ Make sure Flask sees the templates folder
ENV FLASK_APP=server.py
ENV FLASK_RUN_HOST=0.0.0.0

# Point undetected-chromedriver to chromium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Expose app port
EXPOSE 4321

# Start the server with Gunicorn
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:4321", "--workers", "1", "--threads", "4", "--timeout", "300"]
