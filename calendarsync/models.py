"""Data Models for the application."""

import enum
from typing import List

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import String


class Base(DeclarativeBase):
    """Base class for sqlalchemy ORM."""
    

class CalendarSink(Base):
    """Represents the Google calendar to write items to."""

    __tablename__ = "calendar_sink"

    calendar_id: Mapped[str] = mapped_column(String(), primary_key=True)
    sources: Mapped[List["CalendarSource"]] = relationship()

class CalendarSourceType(enum.Enum):
    """The type of calendar this CalendarSource is."""
    GOOGLE_CALENDAR = "google_calendar"
    ICAL = "ical"

class CalendarSource(Base):
    """Represents the Calendar to read items from."""

    __tablename__ = "calendar_source"

    type: Mapped[CalendarSourceType]
    # For ICAL, this is the ICAL link.  For Google Calendar, this is the gcal id.
    calendar_location: Mapped[str] = mapped_column(String(), primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("calendar_sink.calendar_id"))