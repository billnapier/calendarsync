import os
import logging
import firebase_admin
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

# Blueprints
from app.auth import auth_bp
from app.main import main_bp

# Utils
from app.utils import generate_csrf_token, time_ago_filter

# Initialize Firebase Admin SDK
# Skip initialization in development/testing environments to avoid credential errors
if os.environ.get("FLASK_ENV") != "development" and not os.environ.get("TESTING"):
    if not firebase_admin._apps:  # pylint: disable=protected-access
        project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get(
            "GOOGLE_CLOUD_PROJECT"
        )
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            firebase_admin.initialize_app()

app = Flask(__name__)
# Fix for Cloud Run (HTTPS behind proxy)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Firebase Hosting requires the session cookie to be named '__session'
app.config["SESSION_COOKIE_NAME"] = "__session"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # A basic CSP to enhance security. This should be tailored to your app's needs.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://accounts.google.com/gsi/client; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "frame-src 'self' https://accounts.google.com; "
        "connect-src 'self' https://accounts.google.com; "
        "object-src 'none'; "
        "frame-ancestors 'self';"
    )
    # Disable features that are not needed.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Strict-Transport-Security is often handled by the load balancer, but good to have.
    # The 'preload' directive can be added for enhanced security, but requires commitment to HTTPS.
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    return response


logging.basicConfig(level=logging.INFO)

# Configuration
# Allow OAuthlib to use HTTP for local testing
if os.environ.get("FLASK_ENV") == "development" or os.environ.get("FLASK_DEBUG") == "1":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Secret Key
if "SECRET_KEY" in os.environ:
    app.secret_key = os.environ["SECRET_KEY"]
elif (
    os.environ.get("FLASK_ENV") == "development"
    or os.environ.get("FLASK_DEBUG") == "1"
    or os.environ.get("TESTING")
):
    app.secret_key = "dev_key_for_testing_only"
else:
    raise ValueError("No SECRET_KEY set for Flask application")

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)

# Register Context Processors and Filters
app.context_processor(lambda: {"csrf_token": generate_csrf_token()})
app.template_filter("time_ago")(time_ago_filter)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
