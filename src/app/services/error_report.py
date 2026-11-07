from sqlalchemy.orm import Session

from app.models.error_report import ErrorReport
from app.schemas.error_report import ErrorReportUpdate
from app.services.notification import notification_service


class ErrorReportService:
    """Coordinate error-report state changes and their domain notifications."""

    def update(
        self,
        db: Session,
        report_id: int,
        report_update: ErrorReportUpdate,
    ) -> ErrorReport | None:
        report = (
            db.query(ErrorReport)
            .filter(ErrorReport.id == report_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if report is None:
            return None

        update_data = report_update.model_dump(exclude_unset=True)
        became_handled = (
            not report.handled
            and update_data.get("handled") is True
        )

        try:
            for field, value in update_data.items():
                setattr(report, field, value)
            db.add(report)

            if became_handled and report.created_by is not None:
                notification_service.create(
                    db,
                    user_id=report.created_by,
                    notification_type="error_report.handled",
                    title="Votre signalement a été traité",
                    body="Une réponse est disponible dans l'application.",
                    payload={"error_report_id": report.id},
                    commit=False,
                )

            db.commit()
            db.refresh(report)
            return report
        except Exception:
            db.rollback()
            raise


error_report_service = ErrorReportService()
