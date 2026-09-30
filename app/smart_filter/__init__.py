from flask import Blueprint

smart_filter_bp = Blueprint("smart_filter", __name__)

from . import routes  # noqa: E402, F401
