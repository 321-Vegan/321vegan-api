from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer

from app.database.base_class import Base


class VeganuaryWeek(Base):
    """A week of the app's Veganuary course, as the app reads it.

    [content] is the week's JSON, as the app reads it. The course is only
    here (not in the open source app repository): the app downloads it on
    its first visit, then again whenever it changes, without an update.
    """

    __tablename__ = "veganuary_weeks"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, nullable=False, unique=True, index=True)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
