"""Pydantic request/response models."""
from datetime import date
from pydantic import BaseModel, Field


class ActivityOut(BaseModel):
    id: str
    name: str
    slug: str
    tagline: str
    image: str
    is_rooftop_dining: bool

    class Config:
        from_attributes = True


class BayOut(BaseModel):
    id: str
    activity_type_id: str
    name: str
    bay_tier: str
    price_per_session: float
    max_players: int
    description: str
    image: str = ""
    allow_select: bool = True

    class Config:
        from_attributes = True


class SlotOut(BaseModel):
    time: str
    is_available: bool


class FoodOut(BaseModel):
    id: str
    name: str
    description: str
    price: float
    category: str
    image: str

    class Config:
        from_attributes = True


class FoodLine(BaseModel):
    item_id: str
    quantity: int = 1


class BookingCreate(BaseModel):
    activity_id: str
    bay_id: str = ""
    bay_ids: list[str] = Field(default_factory=list)  # multi-bay; falls back to [bay_id]
    date: date
    time: str
    players: int = 1
    guest_name: str = ""
    guest_phone: str = ""
    booking_type: str = "b2c"
    pay_online: bool = False  # client will pay via Razorpay → booking stays pending until verified
    food: list[FoodLine] = Field(default_factory=list)


class BookingResult(BaseModel):
    id: str
    qr_code: str
    pin: str
    total_amount: float
    loyalty_earned: int
    status: str


class ContactInquiryCreate(BaseModel):
    company_name: str
    contact_name: str = ""
    email: str
    phone: str = ""
    license_no: str = ""
    gst_no: str = ""


class ContactInquiryOut(BaseModel):
    id: str
    status: str

    class Config:
        from_attributes = True


class InviteOut(BaseModel):
    token: str
    booking_id: str


class GuestFoodLine(BaseModel):
    name: str
    quantity: int
    item_total: float


class InviteBookingOut(BaseModel):
    """Read-only booking view a guest sees when opening an invite link."""
    booking_id: str
    host_name: str
    activity_name: str
    bay_name: str
    date: date
    time: str
    players: int
    guest_food: list[GuestFoodLine] = Field(default_factory=list)


class GuestFoodAdd(BaseModel):
    guest_name: str = "Guest"
    food: list[FoodLine] = Field(default_factory=list)
    # Payment proof — required when Razorpay is configured (guest pays for their own food).
    razorpay_order_id: str = ""
    razorpay_payment_id: str = ""
    razorpay_signature: str = ""


# ----------------------------- Admin / control panel -----------------------------
class AdminLogin(BaseModel):
    password: str


class ActivityIn(BaseModel):
    name: str
    slug: str
    tagline: str = ""
    image: str = ""
    is_rooftop_dining: bool = False


class BayIn(BaseModel):
    activity_type_id: str
    name: str
    bay_tier: str = "standard"  # standard | vip | vvip
    price_per_session: float
    max_players: int = 6
    description: str = ""
    image: str = ""


class AdminBookingCreate(BaseModel):
    bay_id: str
    date: date
    time: str
    players: int = 1
    guest_name: str = ""
    guest_phone: str = ""
    payment_status: str = "paid"  # paid | pending | complimentary


class DiscountIn(BaseModel):
    code: str
    kind: str = "percent"  # percent | flat
    value: float = 0
    description: str = ""
    active: bool = True


class EventIn(BaseModel):
    name: str
    description: str = ""
    image: str = ""
    event_date: str = ""
    price: float = 0
    active: bool = True


class TierIn(BaseModel):
    activity_type_id: str
    key: str
    name: str
    description: str = ""
    price: float = 0
    time_interval_minutes: int = 60
    allow_select: bool = True


class TierBayCount(BaseModel):
    activity_type_id: str
    key: str
    count: int
    price: float = 0
    max_players: int = 6
    name_prefix: str = ""


class FoodIn(BaseModel):
    name: str
    description: str = ""
    price: float
    category: str = "Burgers"
    image: str = ""


class RazorpayOrderCreate(BaseModel):
    amount: float
    booking_id: str = ""


class RazorpayVerify(BaseModel):
    booking_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class OtpRequest(BaseModel):
    email: str
    purpose: str = "login"


class OtpVerify(BaseModel):
    email: str
    code: str
