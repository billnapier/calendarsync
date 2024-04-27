"""Setup and handle flask-security module."""
import datetime
import uuid

from flask_security import (
    Security,
    SQLAlchemyUserDatastore,
)
from flask_security.models import fsqla_v3 as fsqla

from sqlalchemy import Column, Integer, DateTime

def setup_flask_security(app, db):
    """Configure flask security for use."""
    fsqla.FsModels.set_db_info(db)

    ### The bigquery adapter isn't fully functional.  BigQuery itself doesn't supply an autoincrement feature, so we 
    ### use UUID to simulate it.  bigquery-sqlalchemy doesn't correctly implement func.now() (supposed to be 
    ### CURRENT_DATETIME()), so we generate the timestamps in python.
    def _uid():
        return uuid.uuid4().int & 0x7FFFFFFFFFFFFFFF


    class Role(db.Model, fsqla.FsRoleMixin):
        "Role model."
        id = Column(Integer(), primary_key=True, default=_uid)
        update_datetime = Column(DateTime, default=datetime.datetime.utcnow)


    class User(db.Model, fsqla.FsUserMixin):
        """User model."""
        id = Column(Integer(), primary_key=True, default=_uid)
        create_datetime = Column(DateTime, default=datetime.datetime.utcnow)
        update_datetime = Column(
            DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
        )


    # Setup Flask-Security
    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    app.security = Security(app, user_datastore)