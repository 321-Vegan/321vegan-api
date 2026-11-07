from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification_delivery import NotificationDelivery
from app.models.push_device import PushDevice


class PushDeviceService:
    """Register and deactivate FCM destinations."""

    def register(
        self,
        db: Session,
        *,
        user_id: int,
        platform: str,
        installation_id: str | None,
        token: str,
    ) -> PushDevice:
        """Register a destination, retrying once after a concurrent insert."""
        for attempt in range(2):
            try:
                device = self._register_without_commit(
                    db,
                    user_id=user_id,
                    platform=platform,
                    installation_id=installation_id,
                    token=token,
                )
                db.commit()
                db.refresh(device)
                return device
            except IntegrityError:
                db.rollback()
                if attempt == 1:
                    raise

        raise RuntimeError("Push-device registration retry exhausted")

    def _register_without_commit(
        self,
        db: Session,
        *,
        user_id: int,
        platform: str,
        installation_id: str | None,
        token: str,
    ) -> PushDevice:
        now = datetime.now()
        matches = [PushDevice.token == token]
        if installation_id is not None:
            matches.append(PushDevice.installation_id == installation_id)
        # Match and lock both possible rows in one consistent order. Sending,
        # reassignment and logout all lock the device before its deliveries.
        devices = (
            db.query(PushDevice)
            .filter(or_(*matches))
            .order_by(PushDevice.id)
            .with_for_update()
            .populate_existing()
            .all()
        )
        token_device = next((device for device in devices if device.token == token), None)
        installation_device = next(
            (device for device in devices
             if installation_id is not None and device.installation_id == installation_id),
            None,
        )

        device = token_device or installation_device

        # If a refreshed token already exists on another historical row, retain
        # that row's delivery history and retire the row previously associated
        # with this installation.
        if (
            token_device is not None
            and installation_device is not None
            and token_device.id != installation_device.id
        ):
            self._disable_device(db, installation_device, now)
            installation_device.installation_id = None
            db.add(installation_device)
            db.flush()
            device = token_device

        if device is None:
            device = PushDevice(
                user_id=user_id,
                platform=platform,
                installation_id=installation_id,
                token=token,
                enabled=True,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
        else:
            # A device token belongs to the user currently authenticated on the
            # device. This also safely handles logout followed by another login.
            if device.user_id != user_id:
                self._cancel_outstanding_deliveries(db, device.id, now)
            device.user_id = user_id
            device.platform = platform
            if installation_id is not None:
                device.installation_id = installation_id
            device.token = token
            device.enabled = True
            device.invalidated_at = None
            device.updated_at = now
            device.last_seen_at = now

        db.add(device)
        return device

    def deactivate(
        self,
        db: Session,
        *,
        device_id: int,
        user_id: int,
    ) -> bool:
        device = (
            db.query(PushDevice)
            .filter(
                PushDevice.id == device_id,
                PushDevice.user_id == user_id,
            )
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if device is None:
            return False

        self._disable_device(db, device, datetime.now())
        db.add(device)
        db.commit()
        return True

    def _disable_device(
        self,
        db: Session,
        device: PushDevice,
        now: datetime,
    ) -> None:
        self._cancel_outstanding_deliveries(db, device.id, now)
        device.enabled = False
        device.invalidated_at = now
        device.updated_at = now

    @staticmethod
    def _cancel_outstanding_deliveries(
        db: Session,
        device_id: int,
        now: datetime,
    ) -> None:
        (
            db.query(NotificationDelivery)
            .filter(
                NotificationDelivery.device_id == device_id,
                NotificationDelivery.status.in_(("pending", "retry", "processing")),
            )
            .update(
                {
                    NotificationDelivery.status: "failed",
                    NotificationDelivery.next_attempt_at: None,
                    NotificationDelivery.last_error: "DeviceOwnershipChangedOrDisabled",
                    NotificationDelivery.updated_at: now,
                },
                synchronize_session=False,
            )
        )


push_device_service = PushDeviceService()
