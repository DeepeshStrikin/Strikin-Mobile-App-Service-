"""Strikin API — FastAPI entrypoint.

Run: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Docs: http://localhost:8000/docs
"""
import hashlib
import random
from contextlib import asynccontextmanager
from datetime import date as date_type

# Use the operating-system certificate store for all TLS verification. This keeps
# certificate verification ON (safe against MITM) while still working on machines
# behind a corporate TLS-inspection proxy, whose root CA lives in the OS store but
# not in Python's bundled CA list. On a normal server this is just standard verification.
import truststore as _truststore  # noqa: E402
_truststore.inject_into_ssl()

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .seed import seed

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

_origins = settings.cors_origin_list
_allow_all = not _origins or "*" in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _origins,
    # When allowing all origins, credentials must be disabled per the CORS spec.
    allow_credentials=not _allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api")
def api_root():
    return {"service": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get("/")
def root():
    return {"service": "Strikin API", "status": "ok",
            "control_panel": "/admin", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "healthy", "environment": settings.environment}


# ----------------------------- Activities & Bays -----------------------------
@app.get("/activities", response_model=list[schemas.ActivityOut])
def list_activities(db: Session = Depends(get_db)):
    return db.query(models.ActivityType).all()


@app.get("/activities/{activity_id}/bays", response_model=list[schemas.BayOut])
def list_bays(activity_id: str, db: Session = Depends(get_db)):
    # Accept either the id or the slug for convenience.
    act = (
        db.query(models.ActivityType)
        .filter((models.ActivityType.id == activity_id) | (models.ActivityType.slug == activity_id))
        .first()
    )
    if not act:
        raise HTTPException(404, "Activity not found")
    bays = (
        db.query(models.Bay)
        .filter(models.Bay.activity_type_id == act.id, models.Bay.status != "disabled")
        .all()
    )
    # Surface each tier's allow_select onto its bays (default True = pick specific bay).
    amap = {t.key: t.allow_select for t in
            db.query(models.Tier).filter(models.Tier.activity_type_id == act.id).all()}
    for b in bays:
        b.allow_select = amap.get(b.bay_tier, True)
    return bays


@app.get("/activities/{activity_id}/tiers")
def list_tiers(activity_id: str, db: Session = Depends(get_db)):
    """Tiers for an activity (control panel): merges stored Tier settings with the
    bays grouped under each tier key. Used by the admin Attractions screen."""
    act = (
        db.query(models.ActivityType)
        .filter((models.ActivityType.id == activity_id) | (models.ActivityType.slug == activity_id))
        .first()
    )
    if not act:
        raise HTTPException(404, "Activity not found")
    bays = db.query(models.Bay).filter(models.Bay.activity_type_id == act.id).all()
    stored = {t.key: t for t in db.query(models.Tier).filter(models.Tier.activity_type_id == act.id).all()}
    order = ["standard", "vip", "vvip", "gold"]
    keys = [k for k in order if any(b.bay_tier == k for b in bays) or k in stored]
    keys += [k for k in {b.bay_tier for b in bays} | set(stored) if k not in keys]

    def bay_dict(b):
        return {"id": b.id, "name": b.name, "description": b.description, "image": b.image,
                "max_players": b.max_players, "price_per_session": b.price_per_session,
                "status": b.status}

    out = []
    for key in keys:
        tbays = [b for b in bays if b.bay_tier == key]
        t = stored.get(key)
        price = t.price if t else (tbays[0].price_per_session if tbays else 0)
        out.append({
            "key": key,
            "name": t.name if t else f"{key.upper()} bays",
            "description": t.description if t else "",
            "price": price,
            "time_interval_minutes": t.time_interval_minutes if t else 60,
            "allow_select": t.allow_select if t else True,
            "bays": [bay_dict(b) for b in tbays],
        })
    return {"activity": {"id": act.id, "name": act.name, "slug": act.slug}, "tiers": out}


def _setting(db: Session, key: str, default: str) -> str:
    row = db.query(models.Setting).filter(models.Setting.key == key).first()
    return row.value if (row and row.value) else default


def _expire_stale_pending(db: Session, minutes: int = 20) -> None:
    """Mark unpaid 'pending_payment' bookings older than `minutes` as failed, so they
    show 'payment failed' and stop holding their slot."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = _dt.utcnow() - _td(minutes=minutes)
    stale = (db.query(models.Booking)
             .filter(models.Booking.status == "pending_payment",
                     models.Booking.created_at < cutoff).all())
    changed = False
    for b in stale:
        b.status = "failed"
        b.payment_status = "failed"
        changed = True
    if changed:
        db.commit()


@app.get("/bays/{bay_id}/slots", response_model=list[schemas.SlotOut])
def list_slots(bay_id: str, date: str | None = None, db: Session = Depends(get_db)):
    """Time slots generated from the venue's open/close hours (Settings) stepped by
    the bay's tier interval. Past slots are hidden for today; taken slots are marked."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    # Venue hours from settings (admin-editable), with sensible defaults.
    open_s = _setting(db, "open_time", "11:00 AM")
    close_s = _setting(db, "close_time", "11:00 PM")

    # Slot interval = the bay's tier interval (default 60 min).
    interval = 60
    bay = db.query(models.Bay).filter(models.Bay.id == bay_id).first()
    if bay:
        tier = (db.query(models.Tier)
                .filter(models.Tier.activity_type_id == bay.activity_type_id,
                        models.Tier.key == bay.bay_tier).first())
        if tier and tier.time_interval_minutes:
            interval = tier.time_interval_minutes

    try:
        start = _dt.strptime(open_s, "%I:%M %p")
        end = _dt.strptime(close_s, "%I:%M %p")
    except ValueError:
        start = _dt.strptime("11:00 AM", "%I:%M %p")
        end = _dt.strptime("11:00 PM", "%I:%M %p")

    base_times = []
    t = start
    while t < end:
        base_times.append(t.strftime("%I:%M %p").lstrip("0"))
        t += _td(minutes=max(interval, 15))

    _expire_stale_pending(db)
    taken = set()
    if date:
        try:
            d = date_type.fromisoformat(date)
            rows = (
                db.query(models.Booking)
                .filter(models.Booking.bay_id == bay_id, models.Booking.slot_date == d,
                        models.Booking.status.notin_(["failed", "cancelled"]))
                .all()
            )
            taken = {r.slot_time for r in rows}
        except ValueError:
            pass

    # For TODAY (IST), hide slots whose time has already passed.
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    ist = _tz(_td(hours=5, minutes=30))
    now_ist = _dt.now(ist)
    is_today = date == now_ist.date().isoformat() if date else False

    out = []
    for t in base_times:
        if is_today:
            slot_t = _dt.strptime(t, "%I:%M %p").time()
            if (slot_t.hour, slot_t.minute) <= (now_ist.hour, now_ist.minute):
                continue  # past slot — skip
        out.append(schemas.SlotOut(time=t, is_available=t not in taken))
    return out


@app.get("/food", response_model=list[schemas.FoodOut])
def list_food(db: Session = Depends(get_db)):
    return db.query(models.FoodItem).all()


# ----------------------------- Bookings -----------------------------
@app.post("/bookings", response_model=schemas.BookingResult)
def create_booking(payload: schemas.BookingCreate, db: Session = Depends(get_db)):
    # Resolve the selected bays (multi-bay supported; falls back to a single bay_id).
    bay_ids = payload.bay_ids or ([payload.bay_id] if payload.bay_id else [])
    bays = [db.query(models.Bay).filter(models.Bay.id == bid).first() for bid in bay_ids]
    bays = [b for b in bays if b]
    if not bays:
        raise HTTPException(404, "Bay not found")
    if any(b.status == "disabled" for b in bays):
        raise HTTPException(409, "A selected bay is no longer available — please pick another")
    bay = bays[0]  # primary bay (for the booking's bay_id and activity)

    # Prevent double-booking any selected bay at that date/time.
    _expire_stale_pending(db)
    clash = (
        db.query(models.Booking)
        .filter(
            models.Booking.bay_id.in_([b.id for b in bays]),
            models.Booking.slot_date == payload.date,
            models.Booking.slot_time == payload.time,
            models.Booking.status.notin_(["failed", "cancelled"]),
        )
        .first()
    )
    if clash:
        raise HTTPException(409, "That slot was just taken — please pick another time")

    food_total = 0.0
    food_orders: list[models.BookingFoodOrder] = []
    for line in payload.food:
        fi = db.query(models.FoodItem).filter(models.FoodItem.id == line.item_id).first()
        if not fi:
            continue
        line_total = fi.price * line.quantity
        food_total += line_total
        food_orders.append(
            models.BookingFoodOrder(food_item_id=fi.id, quantity=line.quantity, item_total=line_total)
        )

    bay_total = sum(b.price_per_session for b in bays)
    gross = bay_total + food_total
    rate = settings.default_gst_rate_percent / 100.0
    taxable = round(gross / (1 + rate), 2)
    tax_amount = round(gross - taxable, 2)
    loyalty = int(round(gross * settings.loyalty_earn_rate))

    qr = "STRIKIN-" + "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=8))
    pin = f"{random.randint(1000, 9999)}"

    booking = models.Booking(
        booking_type=payload.booking_type,
        activity_type_id=payload.activity_id if "_" in payload.activity_id else bay.activity_type_id,
        bay_id=bay.id,
        guest_name=payload.guest_name,
        guest_phone=payload.guest_phone,
        slot_date=payload.date,
        slot_time=payload.time,
        players=payload.players,
        total_amount=gross,
        tax_amount=tax_amount,
        qr_code=qr,
        pin=pin,
        loyalty_earned=loyalty,
    )
    booking.activity_type_id = bay.activity_type_id  # always trust the bay's activity
    # If Razorpay is configured, a booking is NOT confirmed until payment is verified
    # (see /payments/razorpay/verify). Without keys (dev), confirm immediately so the
    # app stays usable.
    razorpay_on = bool(settings.razorpay_key_id and settings.razorpay_key_secret) and payload.pay_online
    booking.payment_status = "pending" if razorpay_on else "paid"
    booking.status = "pending_payment" if razorpay_on else "upcoming"
    db.add(booking)
    db.flush()

    # One line item per selected bay.
    for b in bays:
        p = b.price_per_session
        db.add(
            models.BookingItem(
                booking_id=booking.id, bay_id=b.id, item_amount=p,
                tax_amount=round(p - p / (1 + rate), 2),
                cgst=round((p - p / (1 + rate)) / 2, 2),
                sgst=round((p - p / (1 + rate)) / 2, 2),
                hsn_sac_code=settings.gst_hsn_sac_code,
                gst_rate_percent=settings.default_gst_rate_percent,
            )
        )
    for fo in food_orders:
        fo.booking_id = booking.id
        db.add(fo)

    # Only announce "confirmed" if no payment step is pending. When Razorpay is on,
    # the confirmation notification is sent after the payment is verified.
    if not razorpay_on:
        db.add(
            models.Notification(
                recipient=payload.guest_phone or payload.guest_name or "guest",
                channel="whatsapp",
                type="booking_confirmed",
                body=f"Your Strikin booking {booking.id} is confirmed. QR {qr}, PIN {pin}.",
            )
        )
    db.commit()

    return schemas.BookingResult(
        id=booking.id, qr_code=qr, pin=pin, total_amount=gross,
        loyalty_earned=loyalty, status=booking.status,
    )


@app.get("/bookings/{booking_id}", response_model=schemas.BookingResult)
def get_booking(booking_id: str, db: Session = Depends(get_db)):
    b = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not b:
        raise HTTPException(404, "Booking not found")
    return schemas.BookingResult(
        id=b.id, qr_code=b.qr_code, pin=b.pin, total_amount=b.total_amount,
        loyalty_earned=b.loyalty_earned, status=b.status,
    )


# ----------------------------- Invites -----------------------------
@app.post("/bookings/{booking_id}/invite", response_model=schemas.InviteOut)
def create_invite(booking_id: str, db: Session = Depends(get_db)):
    """Create (or return the existing) shareable invite for a booking."""
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    invite = db.query(models.Invite).filter(models.Invite.booking_id == booking_id).first()
    if not invite:
        invite = models.Invite(booking_id=booking_id, host_name=booking.guest_name or "")
        db.add(invite)
        db.commit()
        db.refresh(invite)
    return schemas.InviteOut(token=invite.token, booking_id=booking_id)


@app.get("/invites/{token}", response_model=schemas.InviteBookingOut)
def get_invite(token: str, db: Session = Depends(get_db)):
    """Guest-facing read-only view of a booking opened from an invite link."""
    invite = db.query(models.Invite).filter(models.Invite.token == token).first()
    if not invite:
        raise HTTPException(404, "Invite not found")
    booking = db.query(models.Booking).filter(models.Booking.id == invite.booking_id).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    activity = db.query(models.ActivityType).filter(
        models.ActivityType.id == booking.activity_type_id).first()
    bay = db.query(models.Bay).filter(models.Bay.id == booking.bay_id).first()
    guest_orders = (
        db.query(models.GuestFoodOrder)
        .filter(models.GuestFoodOrder.booking_id == booking.id)
        .all()
    )
    food_lines = []
    for g in guest_orders:
        fi = db.query(models.FoodItem).filter(models.FoodItem.id == g.food_item_id).first()
        food_lines.append(schemas.GuestFoodLine(
            name=f"{g.guest_name}: {fi.name if fi else 'item'}",
            quantity=g.quantity, item_total=g.item_total))
    return schemas.InviteBookingOut(
        booking_id=booking.id,
        host_name=invite.host_name or booking.guest_name or "Your host",
        activity_name=activity.name if activity else "",
        bay_name=bay.name if bay else "",
        date=booking.slot_date,
        time=booking.slot_time,
        players=booking.players,
        guest_food=food_lines,
    )


@app.post("/invites/{token}/food", response_model=schemas.InviteBookingOut)
def add_guest_food(token: str, payload: schemas.GuestFoodAdd, db: Session = Depends(get_db)):
    """A guest adds their own food to the booking via the invite link and pays for it.

    When Razorpay is configured, the guest must pay online first; we verify the payment
    signature here and only then record the food as paid. Without Razorpay (dev), the
    food is recorded directly.
    """
    invite = db.query(models.Invite).filter(models.Invite.token == token).first()
    if not invite:
        raise HTTPException(404, "Invite not found")
    if not payload.food:
        raise HTTPException(400, "No food selected")

    razorpay_on = bool(settings.razorpay_key_id and settings.razorpay_key_secret)
    if razorpay_on:
        if not (payload.razorpay_order_id and payload.razorpay_payment_id and payload.razorpay_signature):
            raise HTTPException(402, "Payment required — guest must pay for their own food")
        if not _razorpay_signature_ok(payload.razorpay_order_id, payload.razorpay_payment_id,
                                      payload.razorpay_signature):
            raise HTTPException(400, "Payment verification failed — invalid signature")

    for line in payload.food:
        fi = db.query(models.FoodItem).filter(models.FoodItem.id == line.item_id).first()
        if not fi or line.quantity < 1:
            continue
        db.add(models.GuestFoodOrder(
            booking_id=invite.booking_id,
            guest_name=payload.guest_name or "Guest",
            food_item_id=fi.id,
            quantity=line.quantity,
            item_total=fi.price * line.quantity,
            payment_status="paid" if razorpay_on else "pending",
        ))
    db.commit()
    return get_invite(token, db)


# ----------------------------- Corporate leads -----------------------------
@app.post("/corporate/inquiries", response_model=schemas.ContactInquiryOut)
def create_inquiry(payload: schemas.ContactInquiryCreate, db: Session = Depends(get_db)):
    lead = models.ContactInquiry(**payload.model_dump())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ----------------------------- OTP / MFA -----------------------------
def _send_via_gmail(to_email: str, code: str) -> bool:
    """Send the OTP via Gmail SMTP using an App Password. No-op if not configured."""
    if not (settings.gmail_user and settings.gmail_app_password):
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(f"Your Strikin OTP is {code}. It is valid for 10 minutes.\n\nIf you didn't request this, ignore this email.")
    msg["Subject"] = "Your Strikin verification code"
    msg["From"] = f"Strikin <{settings.gmail_user}>"
    msg["To"] = to_email
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(settings.gmail_user, settings.gmail_app_password.replace(" ", ""))
            server.sendmail(settings.gmail_user, [to_email], msg.as_string())
        return True
    except Exception:
        return False


def _send_otp_email(to_email: str, code: str) -> bool:
    """Deliver the OTP. Tries Gmail SMTP first, then SendGrid. Returns True if sent."""
    if _send_via_gmail(to_email, code):
        return True
    if not (settings.sendgrid_api_key and settings.sendgrid_from_email):
        return False
    import json as _json
    import urllib.request as _u
    payload = {
        "personalizations": [{"to": [{"email": to_email}], "subject": "Your Strikin verification code"}],
        "from": {"email": settings.sendgrid_from_email, "name": "Strikin"},
        "content": [{
            "type": "text/plain",
            "value": f"Your Strikin OTP is {code}. It is valid for 10 minutes.\n\nIf you didn't request this, ignore this email.",
        }],
    }
    req = _u.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=_json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {settings.sendgrid_api_key}", "Content-Type": "application/json"},
    )
    try:
        import ssl as _s
        ctx = _s.create_default_context()  # verify certs (do NOT disable — MITM risk)
        with _u.urlopen(req, timeout=15, context=ctx) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


@app.post("/auth/otp/request")
def request_otp(payload: schemas.OtpRequest, db: Session = Depends(get_db)):
    code = f"{random.randint(100000, 999999)}"
    db.add(
        models.OtpLog(
            email=payload.email,
            otp_hash=hashlib.sha256(code.encode()).hexdigest(),
            purpose=payload.purpose,
        )
    )
    db.commit()
    emailed = _send_otp_email(payload.email, code)
    resp = {"sent": True, "channel": "email" if emailed else "on_screen"}
    # Only reveal the code on screen when we could NOT actually email it (dev/no key).
    if not emailed:
        resp["debug_code"] = code
    return resp


@app.post("/auth/otp/verify")
def verify_otp(payload: schemas.OtpVerify, db: Session = Depends(get_db)):
    target = hashlib.sha256(payload.code.encode()).hexdigest()
    row = (
        db.query(models.OtpLog)
        .filter(models.OtpLog.email == payload.email, models.OtpLog.status == "pending")
        .order_by(models.OtpLog.created_at.desc())
        .first()
    )
    # Enforce a 10-minute expiry window.
    from datetime import datetime as _dt, timedelta as _td
    if row and row.created_at and row.created_at < _dt.utcnow() - _td(minutes=10):
        row.status = "expired"
        db.commit()
        raise HTTPException(400, "Invalid or expired code")
    # Lock out after 5 failed attempts to stop brute-forcing the 6-digit code.
    if row and row.attempts >= 5:
        row.status = "locked"
        db.commit()
        raise HTTPException(429, "Too many attempts — request a new code")
    if not row or row.otp_hash != target:
        if row:
            row.attempts += 1
            db.commit()
        raise HTTPException(400, "Invalid or expired code")
    row.status = "verified"
    db.commit()
    return {"verified": True}


# ----------------------------- Admin / control panel -----------------------------
def require_admin(x_admin_token: str = Header(default="")):
    """Gate admin endpoints behind the ADMIN_PASSWORD (sent as the X-Admin-Token header)."""
    if not settings.admin_password:
        raise HTTPException(503, "Admin not configured")
    if x_admin_token != settings.admin_password:
        raise HTTPException(401, "Unauthorized")
    return True


@app.post("/admin/login")
def admin_login(payload: schemas.AdminLogin):
    if not settings.admin_password or payload.password != settings.admin_password:
        raise HTTPException(401, "Wrong password")
    # The client stores the password and sends it as X-Admin-Token on each call.
    return {"ok": True, "token": settings.admin_password}


# ---- Activities ----
@app.post("/admin/activities", response_model=schemas.ActivityOut)
def admin_create_activity(payload: schemas.ActivityIn, _: bool = Depends(require_admin),
                          db: Session = Depends(get_db)):
    act = models.ActivityType(**payload.model_dump())
    db.add(act)
    db.commit()
    db.refresh(act)
    return act


@app.put("/admin/activities/{activity_id}", response_model=schemas.ActivityOut)
def admin_update_activity(activity_id: str, payload: schemas.ActivityIn,
                          _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    act = db.query(models.ActivityType).filter(models.ActivityType.id == activity_id).first()
    if not act:
        raise HTTPException(404, "Activity not found")
    for k, v in payload.model_dump().items():
        setattr(act, k, v)
    db.commit()
    db.refresh(act)
    return act


@app.delete("/admin/activities/{activity_id}")
def admin_delete_activity(activity_id: str, _: bool = Depends(require_admin),
                          db: Session = Depends(get_db)):
    if db.query(models.Bay).filter(models.Bay.activity_type_id == activity_id).first():
        raise HTTPException(400, "Delete this activity's bays first")
    act = db.query(models.ActivityType).filter(models.ActivityType.id == activity_id).first()
    if not act:
        raise HTTPException(404, "Activity not found")
    db.delete(act)
    db.commit()
    return {"deleted": activity_id}


# ---- Bays ----
@app.post("/admin/bays", response_model=schemas.BayOut)
def admin_create_bay(payload: schemas.BayIn, _: bool = Depends(require_admin),
                     db: Session = Depends(get_db)):
    bay = models.Bay(**payload.model_dump())
    db.add(bay)
    db.commit()
    db.refresh(bay)
    return bay


@app.put("/admin/bays/{bay_id}", response_model=schemas.BayOut)
def admin_update_bay(bay_id: str, payload: schemas.BayIn, _: bool = Depends(require_admin),
                     db: Session = Depends(get_db)):
    bay = db.query(models.Bay).filter(models.Bay.id == bay_id).first()
    if not bay:
        raise HTTPException(404, "Bay not found")
    for k, v in payload.model_dump().items():
        setattr(bay, k, v)
    db.commit()
    db.refresh(bay)
    return bay


@app.delete("/admin/bays/{bay_id}")
def admin_delete_bay(bay_id: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(models.Booking).filter(models.Booking.bay_id == bay_id).first():
        raise HTTPException(400, "This bay has bookings — cannot delete")
    bay = db.query(models.Bay).filter(models.Bay.id == bay_id).first()
    if not bay:
        raise HTTPException(404, "Bay not found")
    db.delete(bay)
    db.commit()
    return {"deleted": bay_id}


# ---- Tiers ----
@app.post("/admin/tiers")
def admin_upsert_tier(payload: schemas.TierIn, _: bool = Depends(require_admin),
                      db: Session = Depends(get_db)):
    """Create or update a tier. Setting the tier price mirrors it onto all bays in
    that tier so the customer app (per-bay price) stays in sync."""
    t = (db.query(models.Tier)
         .filter(models.Tier.activity_type_id == payload.activity_type_id, models.Tier.key == payload.key)
         .first())
    if not t:
        t = models.Tier(activity_type_id=payload.activity_type_id, key=payload.key, name=payload.name)
        db.add(t)
    t.name = payload.name
    t.description = payload.description
    t.price = payload.price
    t.time_interval_minutes = payload.time_interval_minutes
    t.allow_select = payload.allow_select
    # Mirror price onto this tier's bays.
    for b in db.query(models.Bay).filter(models.Bay.activity_type_id == payload.activity_type_id,
                                         models.Bay.bay_tier == payload.key).all():
        b.price_per_session = payload.price
    db.commit()
    return {"ok": True, "key": payload.key}


@app.post("/admin/tiers/bay-count")
def admin_set_bay_count(payload: schemas.TierBayCount, _: bool = Depends(require_admin),
                        db: Session = Depends(get_db)):
    """Make a tier have exactly `count` bays — auto-creating named bays or removing
    extras (only bays with no bookings can be removed)."""
    existing = (db.query(models.Bay)
                .filter(models.Bay.activity_type_id == payload.activity_type_id,
                        models.Bay.bay_tier == payload.key).all())
    target = max(0, payload.count)
    prefix = payload.name_prefix or f"{payload.key.upper()} Bay"
    # price/capacity: prefer the tier/existing values
    price = payload.price or (existing[0].price_per_session if existing else 0)
    max_players = payload.max_players or (existing[0].max_players if existing else 6)

    if target > len(existing):
        for i in range(len(existing), target):
            db.add(models.Bay(activity_type_id=payload.activity_type_id, name=f"{prefix} {i + 1}",
                              bay_tier=payload.key, price_per_session=price, max_players=max_players,
                              description="", image=existing[0].image if existing else ""))
    elif target < len(existing):
        removable = [b for b in existing
                     if not db.query(models.Booking).filter(models.Booking.bay_id == b.id).first()]
        to_remove = len(existing) - target
        for b in reversed(removable):
            if to_remove <= 0:
                break
            db.delete(b)
            to_remove -= 1
    db.commit()
    n = (db.query(models.Bay)
         .filter(models.Bay.activity_type_id == payload.activity_type_id,
                 models.Bay.bay_tier == payload.key).count())
    return {"count": n}


@app.delete("/admin/tiers")
def admin_delete_tier(activity_type_id: str, key: str, _: bool = Depends(require_admin),
                      db: Session = Depends(get_db)):
    bays = db.query(models.Bay).filter(models.Bay.activity_type_id == activity_type_id,
                                       models.Bay.bay_tier == key).all()
    for b in bays:
        if db.query(models.Booking).filter(models.Booking.bay_id == b.id).first():
            raise HTTPException(400, "A bay in this tier has bookings — cannot delete")
    for b in bays:
        db.delete(b)
    t = (db.query(models.Tier)
         .filter(models.Tier.activity_type_id == activity_type_id, models.Tier.key == key).first())
    if t:
        db.delete(t)
    db.commit()
    return {"deleted": key}


# ---- Food ----
@app.post("/admin/food", response_model=schemas.FoodOut)
def admin_create_food(payload: schemas.FoodIn, _: bool = Depends(require_admin),
                      db: Session = Depends(get_db)):
    item = models.FoodItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.put("/admin/food/{food_id}", response_model=schemas.FoodOut)
def admin_update_food(food_id: str, payload: schemas.FoodIn, _: bool = Depends(require_admin),
                      db: Session = Depends(get_db)):
    item = db.query(models.FoodItem).filter(models.FoodItem.id == food_id).first()
    if not item:
        raise HTTPException(404, "Food item not found")
    for k, v in payload.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/admin/food/{food_id}")
def admin_delete_food(food_id: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(models.FoodItem).filter(models.FoodItem.id == food_id).first()
    if not item:
        raise HTTPException(404, "Food item not found")
    db.delete(item)
    db.commit()
    return {"deleted": food_id}


@app.get("/admin")
def admin_page():
    """Serve the control-panel single-page web app."""
    from fastapi.responses import HTMLResponse
    from .admin_page import ADMIN_HTML
    return HTMLResponse(content=ADMIN_HTML)


# ---- Image upload (stored in DB, served back) ----
@app.post("/admin/upload")
async def admin_upload(file: UploadFile = File(...), _: bool = Depends(require_admin),
                       db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image too large (max 8 MB)")
    asset = models.Asset(content_type=file.content_type or "image/jpeg", data=data)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"url": f"/assets/{asset.id}"}


@app.get("/assets/{asset_id}")
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    from fastapi.responses import Response as _Resp
    asset = db.query(models.Asset).filter(models.Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Not found")
    return _Resp(content=asset.data, media_type=asset.content_type,
                 headers={"Cache-Control": "public, max-age=86400"})


# ---- Admin: create a booking (counter / complimentary) ----
@app.post("/admin/bookings/create")
def admin_create_booking(payload: schemas.AdminBookingCreate, _: bool = Depends(require_admin),
                         db: Session = Depends(get_db)):
    bay = db.query(models.Bay).filter(models.Bay.id == payload.bay_id).first()
    if not bay:
        raise HTTPException(404, "Bay not found")
    complimentary = payload.payment_status == "complimentary"
    gross = 0.0 if complimentary else bay.price_per_session
    rate = settings.default_gst_rate_percent / 100.0
    tax_amount = round(gross - gross / (1 + rate), 2) if gross else 0.0
    loyalty = 0 if complimentary else int(round(gross * settings.loyalty_earn_rate))
    qr = "STRIKIN-" + "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=8))
    pin = f"{random.randint(1000, 9999)}"
    booking = models.Booking(
        booking_type="b2c",
        activity_type_id=bay.activity_type_id,
        bay_id=bay.id,
        guest_name=payload.guest_name,
        guest_phone=payload.guest_phone,
        slot_date=payload.date,
        slot_time=payload.time,
        players=payload.players,
        total_amount=gross,
        tax_amount=tax_amount,
        qr_code=qr,
        pin=pin,
        loyalty_earned=loyalty,
        payment_status="paid" if complimentary else payload.payment_status,
        status="upcoming",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return {"id": booking.id, "qr_code": qr, "pin": pin, "total_amount": gross}


# ---- Reporting (Bookings / Revenue / Dashboard) ----
@app.get("/admin/bookings")
def admin_bookings(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    _expire_stale_pending(db)
    rows = db.query(models.Booking).order_by(models.Booking.created_at.desc()).limit(300).all()
    acts = {a.id: a.name for a in db.query(models.ActivityType).all()}
    bays = {b.id: b.name for b in db.query(models.Bay).all()}
    return [{
        "id": b.id, "guest_name": b.guest_name, "guest_phone": b.guest_phone,
        "activity": acts.get(b.activity_type_id, ""), "bay": bays.get(b.bay_id, ""),
        "date": str(b.slot_date), "time": b.slot_time, "players": b.players,
        "amount": b.total_amount, "payment_status": b.payment_status, "status": b.status,
        "created_at": str(b.created_at),
    } for b in rows]


@app.get("/admin/revenue")
def admin_revenue(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    _expire_stale_pending(db)
    acts = {a.id: a.name for a in db.query(models.ActivityType).all()}
    totals: dict[str, float] = {}  # PAID revenue per activity
    collected = 0.0
    pending_amt = 0.0
    for b in db.query(models.Booking).all():
        name = acts.get(b.activity_type_id, "Other")
        amt = b.total_amount or 0
        if b.payment_status == "paid":
            totals[name] = totals.get(name, 0.0) + amt
            collected += amt
        elif b.payment_status in ("pending", "pending_payment"):
            pending_amt += amt
        # failed bookings are not counted at all
    by_activity = [{"activity": k, "revenue": round(v, 2)} for k, v in sorted(totals.items(), key=lambda x: -x[1])]
    invoices = [{
        "invoice_id": "IN" + b.id[-6:], "customer": b.guest_name or "Guest", "booking_id": b.id,
        "date": str(b.slot_date), "total": b.total_amount, "status": b.payment_status,
    } for b in db.query(models.Booking).order_by(models.Booking.created_at.desc()).limit(100).all()]
    return {"by_activity": by_activity, "total": round(collected, 2),
            "pending": round(pending_amt, 2), "invoices": invoices}


@app.get("/admin/stats")
def admin_stats(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    _expire_stale_pending(db)
    bookings = db.query(models.Booking).all()
    # Revenue = only PAID bookings (failed/pending are not money in hand).
    total_rev = sum(b.total_amount or 0 for b in bookings if b.payment_status == "paid")
    paid = sum(1 for b in bookings if b.payment_status == "paid")
    pending = sum(1 for b in bookings if b.payment_status in ("pending", "pending_payment"))
    return {
        "total_bookings": len(bookings),
        "paid_bookings": paid,
        "pending_bookings": pending,
        "total_revenue": round(total_rev, 2),
        "activities": db.query(models.ActivityType).count(),
        "bays": db.query(models.Bay).count(),
        "food_items": db.query(models.FoodItem).count(),
    }


# ---- Discounts ----
@app.get("/admin/discounts")
def admin_list_discounts(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": d.id, "code": d.code, "kind": d.kind, "value": d.value,
             "description": d.description, "active": d.active}
            for d in db.query(models.Discount).order_by(models.Discount.created_at.desc()).all()]


@app.post("/admin/discounts")
def admin_create_discount(payload: schemas.DiscountIn, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    d = models.Discount(**payload.model_dump())
    db.add(d); db.commit(); db.refresh(d)
    return {"id": d.id}


@app.put("/admin/discounts/{discount_id}")
def admin_update_discount(discount_id: str, payload: schemas.DiscountIn, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.query(models.Discount).filter(models.Discount.id == discount_id).first()
    if not d:
        raise HTTPException(404, "Not found")
    for k, v in payload.model_dump().items():
        setattr(d, k, v)
    db.commit()
    return {"ok": True}


@app.delete("/admin/discounts/{discount_id}")
def admin_delete_discount(discount_id: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.query(models.Discount).filter(models.Discount.id == discount_id).first()
    if d:
        db.delete(d); db.commit()
    return {"deleted": discount_id}


# ---- Events ----
@app.get("/events")
def list_events(db: Session = Depends(get_db)):
    return [{"id": e.id, "name": e.name, "description": e.description, "image": e.image,
             "event_date": e.event_date, "price": e.price}
            for e in db.query(models.Event).filter(models.Event.active == True).order_by(models.Event.created_at.desc()).all()]  # noqa: E712


@app.get("/admin/events")
def admin_list_events(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": e.id, "name": e.name, "description": e.description, "image": e.image,
             "event_date": e.event_date, "price": e.price, "active": e.active}
            for e in db.query(models.Event).order_by(models.Event.created_at.desc()).all()]


@app.post("/admin/events")
def admin_create_event(payload: schemas.EventIn, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    e = models.Event(**payload.model_dump())
    db.add(e); db.commit(); db.refresh(e)
    return {"id": e.id}


@app.put("/admin/events/{event_id}")
def admin_update_event(event_id: str, payload: schemas.EventIn, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not e:
        raise HTTPException(404, "Not found")
    for k, v in payload.model_dump().items():
        setattr(e, k, v)
    db.commit()
    return {"ok": True}


@app.delete("/admin/events/{event_id}")
def admin_delete_event(event_id: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.query(models.Event).filter(models.Event.id == event_id).first()
    if e:
        db.delete(e); db.commit()
    return {"deleted": event_id}


# ---- Corporates ----
@app.get("/admin/corporates")
def admin_corporates(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    companies = [{"id": c.id, "name": c.name, "pan": c.pan_number, "gst": c.gst_number,
                  "size": c.size, "status": c.status} for c in db.query(models.Company).all()]
    inquiries = [{"id": i.id, "company": i.company_name, "contact": i.contact_name, "email": i.email,
                  "phone": i.phone, "status": i.status, "created_at": str(i.created_at)}
                 for i in db.query(models.ContactInquiry).order_by(models.ContactInquiry.created_at.desc()).all()]
    return {"companies": companies, "inquiries": inquiries}


# ---- Communications ----
@app.get("/admin/communications")
def admin_communications(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": n.id, "recipient": n.recipient, "channel": n.channel, "type": n.type,
             "body": n.body, "created_at": str(n.created_at)}
            for n in db.query(models.Notification).order_by(models.Notification.created_at.desc()).limit(200).all()]


# ---- Settings ----
_DEFAULT_SETTINGS = {
    "gst_rate_percent": str(settings.default_gst_rate_percent),
    "loyalty_earn_rate": str(settings.loyalty_earn_rate),
    "gst_hsn_sac_code": settings.gst_hsn_sac_code,
    "venue_name": "Strikin",
    "support_email": settings.sendgrid_from_email or "",
    "open_time": "11:00 AM",
    "close_time": "11:00 PM",
}


@app.get("/admin/settings")
def admin_get_settings(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    stored = {s.key: s.value for s in db.query(models.Setting).all()}
    return {**_DEFAULT_SETTINGS, **stored}


@app.put("/admin/settings")
def admin_put_settings(payload: dict, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    for k, v in payload.items():
        row = db.query(models.Setting).filter(models.Setting.key == k).first()
        if not row:
            row = models.Setting(key=k); db.add(row)
        row.value = str(v)
    db.commit()
    return {"ok": True}


# ----------------------------- Payments (Razorpay) -----------------------------
@app.get("/payments/config")
def payments_config():
    """Tells the app whether real Razorpay checkout is available."""
    return {"razorpay_enabled": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
            "key_id": settings.razorpay_key_id}


def _razorpay_signature_ok(order_id: str, payment_id: str, signature: str) -> bool:
    """Recompute Razorpay's HMAC-SHA256 of `order_id|payment_id` with the key secret
    and compare. Proves a payment is genuine (not forged by the client)."""
    if not settings.razorpay_key_secret:
        return False
    import hmac
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@app.post("/payments/razorpay/order")
def create_razorpay_order(payload: schemas.RazorpayOrderCreate, db: Session = Depends(get_db)):
    """Creates a Razorpay order. The amount is taken from the booking on the SERVER
    (not trusted from the client) — so it always matches the current price and can't
    be tampered with, even if an admin changed the price mid-checkout."""
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise HTTPException(400, "Razorpay not configured — add keys to backend/.env")
    import base64 as _b64
    import json as _json
    import urllib.request as _u
    # Prefer the server-side booking total; fall back to the requested amount.
    amount = payload.amount
    if payload.booking_id:
        booking = db.query(models.Booking).filter(models.Booking.id == payload.booking_id).first()
        if booking:
            amount = booking.total_amount
    body = _json.dumps({
        "amount": int(round(amount * 100)),  # paise
        "currency": "INR",
        "receipt": payload.booking_id or "strikin",
    }).encode()
    auth = _b64.b64encode(f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()).decode()
    req = _u.Request("https://api.razorpay.com/v1/orders", data=body,
                     headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    try:
        import ssl as __ssl
        ctx = __ssl.create_default_context()  # verify certs — payment traffic must be MITM-safe
        with _u.urlopen(req, timeout=15, context=ctx) as r:
            import json as __j
            return __j.load(r)
    except Exception as e:
        raise HTTPException(502, f"Razorpay error: {e}")


@app.get("/payments/checkout")
def razorpay_checkout_page(order_id: str, amount: int, name: str = "", email: str = "",
                           contact: str = "", description: str = "Strikin booking"):
    """A minimal HTML page that runs Razorpay Checkout and reports the result back to
    the app's WebView via a `StrikinPay` JavaScript channel. Used for in-app payment
    on mobile (web uses checkout.js directly)."""
    import html as _html
    from fastapi.responses import HTMLResponse
    key = settings.razorpay_key_id or ""
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strikin Payment</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>html,body{{margin:0;height:100%;background:#191919;color:#E5E8EA;font-family:sans-serif;
display:flex;align-items:center;justify-content:center}}</style></head>
<body><div>Opening secure payment…</div><script>
function send(msg){{ if(window.StrikinPay&&window.StrikinPay.postMessage){{window.StrikinPay.postMessage(JSON.stringify(msg));}} }}
var opts = {{
  "key": "{_html.escape(key)}",
  "order_id": "{_html.escape(order_id)}",
  "amount": {int(amount)},
  "currency": "INR",
  "name": "Strikin",
  "description": "{_html.escape(description)}",
  "prefill": {{"name":"{_html.escape(name)}","email":"{_html.escape(email)}","contact":"{_html.escape(contact)}"}},
  "theme": {{"color":"#D6FD31"}},
  "handler": function(r){{ send({{"payment_id":r.razorpay_payment_id,"order_id":r.razorpay_order_id,"signature":r.razorpay_signature}}); }},
  "modal": {{"ondismiss": function(){{ send({{"dismissed":true}}); }}}}
}};
try {{ var rzp = new Razorpay(opts); rzp.open(); }} catch(e){{ send({{"error":String(e)}}); }}
</script></body></html>"""
    return HTMLResponse(content=page)


@app.post("/payments/razorpay/verify")
def verify_razorpay_payment(payload: schemas.RazorpayVerify, db: Session = Depends(get_db)):
    """Verify a Razorpay payment signature and ONLY THEN confirm the booking.

    Razorpay signs `order_id|payment_id` with HMAC-SHA256 using your key secret.
    Recomputing it server-side proves the payment is genuine and was not forged by
    the client. Without this check, anyone could claim a booking is paid.
    """
    if not settings.razorpay_key_secret:
        raise HTTPException(400, "Razorpay not configured")
    if not _razorpay_signature_ok(payload.razorpay_order_id, payload.razorpay_payment_id,
                                  payload.razorpay_signature):
        raise HTTPException(400, "Payment verification failed — invalid signature")

    booking = db.query(models.Booking).filter(models.Booking.id == payload.booking_id).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    booking.payment_status = "paid"
    booking.status = "upcoming"
    db.add(models.Notification(
        recipient=booking.guest_phone or booking.guest_name or "guest",
        channel="whatsapp", type="payment_confirmed",
        body=f"Payment received for booking {booking.id}. QR {booking.qr_code}, PIN {booking.pin}.",
    ))
    db.commit()
    return {"verified": True, "booking_id": booking.id,
            "qr_code": booking.qr_code, "pin": booking.pin, "status": booking.status}


# ----------------------------- Image proxy -----------------------------
# Fetches remote images server-side and serves them same-origin, so they always
# render on web (no CORS issues) and on the phone (even if it can't reach the host).
import ssl as _ssl  # noqa: E402
import urllib.request as _urlreq  # noqa: E402
from fastapi import Response  # noqa: E402

_img_cache: dict[str, tuple[bytes, str]] = {}
_img_ctx = _ssl.create_default_context()  # verify certs

# SSRF guard: only proxy https images from known-good public hosts, and never
# anything that resolves to a private / loopback / link-local address.
import ipaddress as _ipaddr  # noqa: E402
import socket as _socket  # noqa: E402
from urllib.parse import urlparse as _urlparse  # noqa: E402

def _is_safe_image_url(u: str) -> bool:
    """Allow any public HTTPS image, but block the real SSRF risk: hosts that
    resolve to internal / private / loopback / link-local / reserved addresses
    (e.g. cloud metadata endpoints or internal services)."""
    try:
        p = _urlparse(u)
        if p.scheme != "https" or not p.hostname:
            return False
        for info in _socket.getaddrinfo(p.hostname, None):
            ip = _ipaddr.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False


@app.get("/img")
def image_proxy(u: str):
    if not _is_safe_image_url(u):
        raise HTTPException(400, "image host not allowed")
    if u in _img_cache:
        data, ct = _img_cache[u]
    else:
        try:
            req = _urlreq.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with _urlreq.urlopen(req, timeout=12, context=_img_ctx) as r:
                data = r.read()
                ct = r.headers.get("Content-Type", "image/jpeg")
            if len(_img_cache) < 300:
                _img_cache[u] = (data, ct)
        except Exception:
            raise HTTPException(502, "image fetch failed")
    return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})


# ----------------------------- Serve the built Flutter web app -----------------------------
# When `strikin_flutter/build/web` exists (after `flutter build web`), serve it at "/" so the
# whole product (app + API + database) is a single live origin. Mounted last so every API
# route above takes precedence over the static handler.
import os  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_WEB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "strikin_flutter", "build", "web")
)


@app.get("/strikin.apk")
def download_apk():
    """Serve the Android APK with the correct headers so phones install it."""
    path = os.path.join(_WEB_DIR, "strikin.apk")
    if not os.path.isfile(path):
        raise HTTPException(404, "APK not built yet")
    return FileResponse(
        path,
        media_type="application/vnd.android.package-archive",
        filename="strikin.apk",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
