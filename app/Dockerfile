FROM python:3.12-slim

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /workspace

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code into app/ directory to preserve package structure
COPY . app/

# Set PYTHONPATH so 'app' package is discoverable
ENV PYTHONPATH=/workspace

# Change ownership of the workspace to the new user
RUN chown -R appuser:appgroup /workspace

# Switch to the non-root user
USER appuser

# Run the web service
# Point to app.app module (app package -> app.py module -> app instance)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app.app:app
