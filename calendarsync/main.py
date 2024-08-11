"""Main module for running webserver."""

import os

import config
import models
from flask import Flask, render_template, redirect, url_for
from flask_bootstrap import Bootstrap
from flask_security import (
    auth_required,
)
from flask_sqlalchemy import SQLAlchemy
from security import setup_flask_security
from werkzeug.middleware.proxy_fix import ProxyFix
from wtforms import StringField, validators
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import Session

# Create app
app = Flask(__name__)

if app.config["DEBUG"]:
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_host=1, x_port=1, x_proto=1, x_prefix=1
    )


app.config["WTF_CSRF_CHECK_DEFAULT"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = dict(pool_pre_ping=True)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECURITY_REGISTERABLE"] = False
app.config["SECURITY_OAUTH_ENABLE"] = True
app.config["SECURITY_SEND_REGISTER_EMAIL"] = False
app.config["SECURITY_PASSWORD_REQUIRED"] = False
app.config["SECURITY_OAUTH_BUILTIN_PROVIDERS"] = ["google"]

app_config = config.Config()

# Generate a nice key using secrets.token_urlsafe()
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", app_config.access_secret("flask_secret_key")
)
# Bcrypt is set as default SECURITY_PASSWORD_HASH, which requires a salt
# Generate a good salt using: secrets.SystemRandom().getrandbits(128)
app.config["SECURITY_PASSWORD_SALT"] = os.environ.get(
    "SECURITY_PASSWORD_SALT", app_config.access_secret("flask_password_salt")
)
app.config["GOOGLE_CLIENT_ID"] = app_config.access_secret("google_oauth_client_id")
app.config["GOOGLE_CLIENT_SECRET"] = app_config.access_secret(
    "google_oauth_client_secret"
)
app.config["SQLALCHEMY_DATABASE_URI"] = app_config.sqlalchemy_database_uri


db = SQLAlchemy(app)
setup_flask_security(app=app, db=db)

Bootstrap(app)


# Views
@app.route("/")
@auth_required()
def home():
    """Home page."""
    return render_template("index.html")


class AddCalendarForm(FlaskForm):
    source_url = StringField(
        "Source URL",
        [validators.URL(message="The source URL provided is invalid")])
    dest_cal_id = StringField(
        "Destination Google Calendar Id",
        [validators.Length(min=6, max=35, message="The Google Calendar Id is invalid")],
    )


@app.route("/calendar/add", methods=["POST"])
@auth_required()
def new_calendar():
    """Add a new calendar sink for the user."""
    form = AddCalendarForm()
    if form.validate_on_submit():
        with Session(db.engine) as session:
            c = models.Calendar(calendar_location=form.source_url.data, destination_calendar=form.dest_cal_id.data)
            session.add_all(c)
            session.commit()

        return redirect(url_for("home"))
    return render_template("new_calendar.html", form=form)


if __name__ == "__main__":
    app.run(debug=True)
