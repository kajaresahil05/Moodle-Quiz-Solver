# Use official Playwright image with pre-installed Chromium and system dependencies
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BROWSER_HEADLESS=true \
    APP_HOST=0.0.0.0 \
    APP_PORT=10000

WORKDIR /app

# Install Python dependencies first for caching efficiency
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Ensure Playwright Chromium browser is installed
RUN playwright install chromium

# Copy application files
COPY . .

# Expose port (Render sets $PORT dynamically)
EXPOSE 10000

# Start FastAPI application
CMD ["python", "run.py"]
