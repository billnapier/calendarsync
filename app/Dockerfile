FROM python:3.12-slim

WORKDIR /workspace

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code into app/ directory to preserve package structure
COPY . app/

# Set PYTHONPATH so 'app' package is discoverable
ENV PYTHONPATH=/workspace

# Run the web service
# Point to app.app module (app package -> app.py module -> app instance)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app.app:app
