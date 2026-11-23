from sqlalchemy import Column, Date, ForeignKey, Integer, String

from app.database.base_class import Base


class VeganuaryDay(Base):
    """A day of the Veganuary course done by a user: the app keeps its
    progress here too, to get it back on another device (or after a
    reinstall), and for statistics.

    Kept small (one row per user and day done, for tens of thousands of
    users): the user and the day are the key, its index also finds a
    user's days; no id nor timestamps, completed_on says when.
    """

    __tablename__ = "veganuary_days"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Number in the whole course (1 to 31)
    day = Column(Integer, primary_key=True)
    # The user's local date it was done: the next days open from it
    completed_on = Column(Date, nullable=False)
    # The idée reçue picked that day, if any
    myth_id = Column(String(64), nullable=True)
