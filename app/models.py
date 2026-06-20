"""SQLAlchemy models — a representative subset of the Strikin 33-table schema,
covering the tables the mobile app exercises end-to-end."""
import uuid
from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ActivityType(Base):
    __tablename__ = "activity_types"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("act"))
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String, unique=True)
    tagline: Mapped[str] = mapped_column(String, default="")
    image: Mapped[str] = mapped_column(String, default="")
    is_rooftop_dining: Mapped[bool] = mapped_column(Boolean, default=False)

    bays: Mapped[list["Bay"]] = relationship(back_populates="activity")


class Bay(Base):
    __tablename__ = "bays"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("bay"))
    activity_type_id: Mapped[str] = mapped_column(ForeignKey("activity_types.id"))
    name: Mapped[str] = mapped_column(String)
    bay_tier: Mapped[str] = mapped_column(String, default="standard")  # standard | vvip
    price_per_session: Mapped[float] = mapped_column(Float)
    max_players: Mapped[int] = mapped_column(Integer, default=6)
    description: Mapped[str] = mapped_column(String, default="")
    image: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="available")

    activity: Mapped[ActivityType] = relationship(back_populates="bays")


class Tier(Base):
    """A pricing tier within an activity (e.g. 'VVIP bays', 'Standard bays').
    Holds tier-level settings shown in the control panel. Bays belong to a tier
    via (activity_type_id + key); the tier price is mirrored onto its bays so the
    customer app (which reads per-bay price) keeps working unchanged."""
    __tablename__ = "tiers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("tier"))
    activity_type_id: Mapped[str] = mapped_column(ForeignKey("activity_types.id"))
    key: Mapped[str] = mapped_column(String)  # standard | vip | vvip | custom slug
    name: Mapped[str] = mapped_column(String)  # display name, e.g. "VVIP bays"
    description: Mapped[str] = mapped_column(String, default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    time_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    allow_select: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FoodItem(Base):
    """Proxy for Restoworks menu master data."""
    __tablename__ = "food_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("food"))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    price: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String, default="Burgers")
    image: Mapped[str] = mapped_column(String, default="")


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("co"))
    name: Mapped[str] = mapped_column(String)
    pan_number: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String, nullable=True)
    size: Mapped[str] = mapped_column(String, default="11-50")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|active|suspended
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContactInquiry(Base):
    """Corporate onboarding leads."""
    __tablename__ = "contact_inquiries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("lead"))
    company_name: Mapped[str] = mapped_column(String)
    contact_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String, default="")
    license_no: Mapped[str] = mapped_column(String, default="")
    gst_no: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="new")  # new|contacted|closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("BK"))
    booking_type: Mapped[str] = mapped_column(String, default="b2c")  # corporate|b2c|guest
    activity_type_id: Mapped[str] = mapped_column(ForeignKey("activity_types.id"))
    bay_id: Mapped[str] = mapped_column(ForeignKey("bays.id"))
    guest_name: Mapped[str] = mapped_column(String, default="")
    guest_phone: Mapped[str] = mapped_column(String, default="")
    slot_date: Mapped[date] = mapped_column(Date)
    slot_time: Mapped[str] = mapped_column(String)
    players: Mapped[int] = mapped_column(Integer, default=1)
    total_amount: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    payment_status: Mapped[str] = mapped_column(String, default="confirmed")
    status: Mapped[str] = mapped_column(String, default="upcoming")
    # The Razorpay order created for THIS booking. Bound at order-creation so payment
    # verification can confirm the guest paid the order we made (correct amount) and
    # not a cheaper order they created separately.
    razorpay_order_id: Mapped[str] = mapped_column(String, default="")
    qr_code: Mapped[str] = mapped_column(String, default="")
    pin: Mapped[str] = mapped_column(String, default="")
    loyalty_earned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[list["BookingItem"]] = relationship(back_populates="booking", cascade="all, delete-orphan")
    food_orders: Mapped[list["BookingFoodOrder"]] = relationship(back_populates="booking", cascade="all, delete-orphan")


class BookingItem(Base):
    __tablename__ = "booking_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("bi"))
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
    bay_id: Mapped[str] = mapped_column(ForeignKey("bays.id"))
    item_amount: Mapped[float] = mapped_column(Float)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    cgst: Mapped[float] = mapped_column(Float, default=0)
    sgst: Mapped[float] = mapped_column(Float, default=0)
    igst: Mapped[float] = mapped_column(Float, default=0)
    hsn_sac_code: Mapped[str] = mapped_column(String, default="")
    gst_rate_percent: Mapped[float] = mapped_column(Float, default=18)

    booking: Mapped[Booking] = relationship(back_populates="items")


class BookingFoodOrder(Base):
    __tablename__ = "booking_food_orders"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("bfo"))
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_total: Mapped[float] = mapped_column(Float)

    booking: Mapped[Booking] = relationship(back_populates="food_orders")


class OtpLog(Base):
    __tablename__ = "otp_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("otp"))
    email: Mapped[str] = mapped_column(String)
    otp_hash: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String, default="login")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invite(Base):
    """A shareable invite for a booking. The host shares the token; guests open it
    to view the booking and add their own (postpaid) food."""
    __tablename__ = "invites"
    token: Mapped[str] = mapped_column(String, primary_key=True,
                                       default=lambda: uuid.uuid4().hex[:20])
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
    host_name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GuestFoodOrder(Base):
    """Food a guest adds to a booking via an invite link. The guest pays for their
    own food online (Razorpay), so it is tracked separately from the host's order."""
    __tablename__ = "guest_food_orders"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("gfo"))
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
    guest_name: Mapped[str] = mapped_column(String, default="")
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_total: Mapped[float] = mapped_column(Float, default=0)
    payment_status: Mapped[str] = mapped_column(String, default="pending")  # pending|paid
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Discount(Base):
    __tablename__ = "discounts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("disc"))
    code: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="percent")  # percent | flat
    value: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("evt"))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    image: Mapped[str] = mapped_column(String, default="")
    event_date: Mapped[str] = mapped_column(String, default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Editable key/value settings managed from the control panel."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, default="")


class Asset(Base):
    """Uploaded images (e.g. bay/activity/food photos from the control panel),
    stored in the DB so they survive restarts and don't need external file storage."""
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("img"))
    content_type: Mapped[str] = mapped_column(String, default="image/jpeg")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("ntf"))
    recipient: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String, default="email")  # email|sms|whatsapp|in_app
    type: Mapped[str] = mapped_column(String, default="booking_confirmed")
    body: Mapped[str] = mapped_column(Text, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
