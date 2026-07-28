from sqlalchemy.orm import Session
from app.notifications.models import DischargeNotification

TARGET_MODULES = ["pharmacy", "billing", "nursing"]


def queue_discharge_notifications(db: Session, discharge):
    rows = [
        DischargeNotification(
            discharge_id=discharge.id,
            target_module=module,
            status="queued",
        )
        for module in TARGET_MODULES
    ]
    db.add_all(rows)
    db.commit()
    return rows