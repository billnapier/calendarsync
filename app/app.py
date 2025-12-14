"""
Simple Flask application for CalendarSync.
"""
import os
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    """Render the home page."""
    return render_template('index.html')

if __name__ == '__main__':
    # Cloud Run sets PORT environment variable, default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
