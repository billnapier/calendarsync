import os

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_security import (
    Security,
    SQLAlchemyUserDatastore,
    auth_required,
)
from flask_security.models import fsqla_v3 as fsqla

import datetime
import uuid
from sqlalchemy import Column, Integer, DateTime

import config

# Create app
app = Flask(__name__)

if app.config["DEBUG"]:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_port=1, x_proto=1, x_prefix=1)

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
    "SECRET_KEY", app_config.access_secret('flask_secret_key')
)
# Bcrypt is set as default SECURITY_PASSWORD_HASH, which requires a salt
# Generate a good salt using: secrets.SystemRandom().getrandbits(128)
app.config["SECURITY_PASSWORD_SALT"] = os.environ.get(
    "SECURITY_PASSWORD_SALT", app_config.access_secret('flask_password_salt')
)
app.config["GOOGLE_CLIENT_ID"] = app_config.access_secret('google_oauth_client_id')
app.config["GOOGLE_CLIENT_SECRET"] = app_config.access_secret('google_oauth_client_secret')
app.config["SQLALCHEMY_DATABASE_URI"] = app_config.sqlalchemy_database_uri

db = SQLAlchemy(app)
fsqla.FsModels.set_db_info(db)

### The bigquery adapter isn't fully functional.  BigQuery itself doesn't supply an autoincrement feature, so we 
### use UUID to simulate it.  bigquery-sqlalchemy doesn't correctly implement func.now() (supposed to be 
### CURRENT_DATETIME()), so we generate the timestamps in python.
def _uid():
    return uuid.uuid4().int & 0x7FFFFFFFFFFFFFFF


class Role(db.Model, fsqla.FsRoleMixin):
    id = Column(Integer(), primary_key=True, default=_uid)
    update_datetime = Column(DateTime, default=datetime.datetime.utcnow)


class User(db.Model, fsqla.FsUserMixin):
    id = Column(Integer(), primary_key=True, default=_uid)
    create_datetime = Column(DateTime, default=datetime.datetime.utcnow)
    update_datetime = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


# Setup Flask-Security
user_datastore = SQLAlchemyUserDatastore(db, User, Role)
app.security = Security(app, user_datastore)

# Views
@app.route("/")
@auth_required()
def home():
    return render_template_string("Hello {{ current_user.email }}")

if __name__ == "__main__":
    app.run()
