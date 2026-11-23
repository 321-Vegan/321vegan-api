from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer

from app.database.base_class import Base


class VeganuaryWeek(Base):
    """A week of the app's Veganuary course, as the app reads it.

    [content] is the week's JSON, the same as the app's bundled
    `lib/assets/veganuary/weekN.json`: editing it here changes the course
    without an app update (the app keeps its bundled copy as a fallback).
    """

    __tablename__ = "veganuary_weeks"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, nullable=False, unique=True, index=True)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
