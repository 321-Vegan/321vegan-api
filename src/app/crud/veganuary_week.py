from datetime import datetime
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crud.base import CRUDRepository
from app.models.veganuary_week import VeganuaryWeek


class VeganuaryWeekRepository(CRUDRepository):
    def get_all_ordered(self, db: Session):
        return db.query(VeganuaryWeek).order_by(VeganuaryWeek.number).all()

    def version(self, db: Session) -> str | None:
        """The latest change and the number of weeks: a week removed
        changes it too."""
        latest, count = db.query(
            func.max(VeganuaryWeek.updated_at), func.count(VeganuaryWeek.id)
        ).one()
        if latest is None:
            return None
        return f"{latest.isoformat()}-{count}"

    def upsert(self, db: Session, number: int, content: Dict[str, Any]) -> VeganuaryWeek:
        week = self.get_one(db, VeganuaryWeek.number == number)
        if week is None:
            week = VeganuaryWeek(number=number, content=content)
            db.add(week)
        else:
            week.content = content
            # The JSON column isn't tracked in place: set the date ourselves
            week.updated_at = datetime.now()
        db.commit()
        db.refresh(week)
        return week


veganuary_week_crud = VeganuaryWeekRepository(model=VeganuaryWeek)
