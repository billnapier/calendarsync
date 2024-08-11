"""Data Models for the application."""

import enum
from typing import List

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import String


class Base(DeclarativeBase):
    """Base class for sqlalchemy ORM."""
    

class CalendarSourceType(enum.Enum):
    """The type of calendar this CalendarSource is."""
    GOOGLE_CALENDAR = "google_calendar"
    ICAL = "ical"

class Calendar(Base):
    """Represents the Calendar to read items from."""

    __tablename__ = "calendar_source"

    type: Mapped[CalendarSourceType]
    # For ICAL, this is the ICAL link.  For Google Calendar, this is the gcal id.
    calendar_location: Mapped[str] = mapped_column(String(), primary_key=True)
    # The google calendar we are writing to
    destination_calendar: Mapped[str] = mapped_column(String(), primary_key=True)