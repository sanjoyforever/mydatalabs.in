# Use minimal Python 3.12 slim image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    FLASK_ENV=production

# Set working directory inside container
WORKDIR /app

# Install system dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure static assets are synced to public/static directory
RUN python update_data.py

# Expose default port
EXPOSE 8080

# Healthcheck to verify container responsiveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8080}/ || exit 1

# Run Gunicorn WSGI Production Server using dynamic PORT env
CMD exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 4 --threads 2 "app:create_app()"
