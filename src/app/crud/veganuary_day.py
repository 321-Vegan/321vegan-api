from datetime import date
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud.base import CRUDRepository
from app.models.veganuary_day import VeganuaryDay


class VeganuaryDayRepository(CRUDRepository):
    def get_by_user(self, db: Session, user_id: int) -> List[VeganuaryDay]:
        return (
            db.query(VeganuaryDay)
            .filter(VeganuaryDay.user_id == user_id)
            .order_by(VeganuaryDay.day)
            .all()
        )

    def save(
        self,
        db: Session,
        user_id: int,
        day: int,
        completed_on: date,
        myth_id: Optional[str],
        retry: bool = True,
    ) -> VeganuaryDay:
        """Records [day] as done, again without harm (a retried request, two
        devices): the earliest date and the idée reçue known are kept."""
        record = self.get_one(
            db, VeganuaryDay.user_id == user_id, VeganuaryDay.day == day
        )
        if record is not None:
            record.completed_on = min(record.completed_on, completed_on)
            record.myth_id = myth_id or record.myth_id
            db.commit()
            db.refresh(record)
            return record

        record = VeganuaryDay(
            user_id=user_id, day=day, completed_on=completed_on, myth_id=myth_id
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            # Saved at the same moment by another request (two devices, a
            # retry): updated instead
            db.rollback()
            if not retry:
                raise
            return self.save(db, user_id, day, completed_on, myth_id, retry=False)
        db.refresh(record)
        return record

    def delete_by_user(self, db: Session, user_id: int) -> None:
        db.query(VeganuaryDay).filter(VeganuaryDay.user_id == user_id).delete()
        db.commit()


veganuary_day_crud = VeganuaryDayRepository(model=VeganuaryDay)
