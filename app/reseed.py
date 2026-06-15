"""One-time re-seed: wipe the activity/bay/food catalog and re-create it from
seed.py (the new Standard/VIP/VVIP structure).

⚠️ This also clears existing bookings, because bookings reference bays by id and
those ids change when bays are recreated. Safe for a pre-launch / test database.

Run from the backend folder:
    .venv\\Scripts\\python.exe -m app.reseed
"""
from sqlalchemy import text

from .database import SessionLocal, engine, Base
from . import models  # noqa: F401  (ensures all tables are registered)
from .seed import seed

# Delete in FK-safe order (children first). invites + guest_food_orders reference
# bookings, so they must go before bookings.
_TABLES_IN_ORDER = [
    "guest_food_orders",
    "invites",
    "booking_food_orders",
    "booking_items",
    "bookings",
    "bays",
    "food_items",
    "activity_types",
]


def reseed() -> None:
    Base.metadata.create_all(bind=engine)  # make sure tables exist
    db = SessionLocal()
    try:
        for table in _TABLES_IN_ORDER:
            db.execute(text(f"DELETE FROM {table}"))
        db.commit()
        print("Cleared old catalog + bookings.")
        seed(db)
        n_act = db.query(models.ActivityType).count()
        n_bay = db.query(models.Bay).count()
        print(f"Re-seeded: {n_act} activities, {n_bay} bays (Standard/VIP/VVIP).")
    finally:
        db.close()


if __name__ == "__main__":
    reseed()
