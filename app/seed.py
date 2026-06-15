"""Idempotent seed data — activities, bays, and Restoworks-style food menu.
Images are the real strikin.com (Sanity CDN) renders."""
from sqlalchemy.orm import Session

from . import models

_CDN = "https://cdn.sanity.io/images/y370h02s/production"
IMG_GOLF = f"{_CDN}/b0a99393be83b97e331bc07e61a01263e849c96f-3840x2160.png?w=800&q=75"
IMG_GOLF2 = f"{_CDN}/d4241f3621d606af26e807be55d88ca3a6f0b0fd-3840x2160.png?w=800&q=75"
IMG_GOLF3 = f"{_CDN}/71e81a78436e02aaf23d578651cef57bf3cc51d7-1920x1080.png?w=800&q=75"
IMG_GOLF4 = f"{_CDN}/f9807ea536c4b2ad91bb43b87894fda1ec48e65a-1920x890.png?w=800&q=75"
IMG_CRICKET = f"{_CDN}/9c0cefc60358879dfff6ec15cb11e8158ab3cfee-2560x1703.png?w=800&q=75"
IMG_DINING = f"{_CDN}/b665e9badcb7e0f69c71fc556ac5b6b5ec8f5d91-1920x1080.png?w=800&q=75"
IMG_DINING2 = f"{_CDN}/a8442a480ff132a8ad0c9622b0b4c0cf4d8f2aa8-5436x3624.jpg?w=800&q=75"
IMG_DINING3 = f"{_CDN}/a4d76bf96e4eea0fb9eb787f6633833eaf93fc28-1920x1080.png?w=800&q=75"
IMG_SCREEN = f"{_CDN}/f78bdb4711e2855bf0378d3501adb3d7a341cd0e-2560x1600.png?w=800&q=75"
IMG_SCREEN2 = f"{_CDN}/5a3ec114d7979ce79d247b891756c3bc2241537d-2560x1600.jpg?w=800&q=75"


def seed(db: Session) -> None:
    if db.query(models.ActivityType).first():
        return

    golf = models.ActivityType(
        name="Golf Bays", slug="golf",
        tagline="Play your way and lounge easy with social golf.",
        image=IMG_GOLF,
    )
    cricket = models.ActivityType(
        name="Cricket Bays", slug="cricket",
        tagline="Tech-Powered Cricket. Gully Roots. New-Age Thrills.",
        image=IMG_CRICKET,
    )
    dining = models.ActivityType(
        name="Rooftop Dining", slug="rooftop-dining", is_rooftop_dining=True,
        tagline="Skyline views, craft plates & cocktails.",
        image=IMG_DINING,
    )
    screening = models.ActivityType(
        name="Private Screening", slug="screening",
        tagline="Book the big screen for your crew.",
        image=IMG_SCREEN,
    )
    db.add_all([golf, cricket, dining, screening])
    db.flush()

    # Bay catalog — exactly three tiers everywhere: Standard, VIP, VVIP.
    # Prices/player-limits follow the Figma (Golf: Standard ₹2,500 · VVIP ₹5,000).
    db.add_all([
        # ---- Golf ----
        models.Bay(activity_type_id=golf.id, name="Standard Bay", bay_tier="standard",
                   price_per_session=2500, max_players=6,
                   description="Level up your game — perfect for groups of 6",
                   image=IMG_GOLF3),
        models.Bay(activity_type_id=golf.id, name="VIP Bay", bay_tier="vip",
                   price_per_session=3800, max_players=8,
                   description="Premium turf, lounge seating & a dedicated host",
                   image=IMG_GOLF2),
        models.Bay(activity_type_id=golf.id, name="Four Seasons Room", bay_tier="vvip",
                   price_per_session=5000, max_players=10,
                   description="All four seasons, one sensory bay",
                   image=IMG_GOLF),
        models.Bay(activity_type_id=golf.id, name="Space Room", bay_tier="vvip",
                   price_per_session=5000, max_players=10,
                   description="Interstellar luxury bay",
                   image=IMG_GOLF4),
        # ---- Cricket ----
        models.Bay(activity_type_id=cricket.id, name="Standard Net", bay_tier="standard",
                   price_per_session=2500, max_players=6,
                   description="Level up your game — perfect for groups of 6",
                   image=IMG_CRICKET),
        models.Bay(activity_type_id=cricket.id, name="VIP Net", bay_tier="vip",
                   price_per_session=3500, max_players=6,
                   description="Pro-grade net with bowling machine & analytics",
                   image=IMG_CRICKET),
        models.Bay(activity_type_id=cricket.id, name="VVIP Net", bay_tier="vvip",
                   price_per_session=5000, max_players=6,
                   description="The ultimate net — premium turf, lounge & host",
                   image=IMG_CRICKET),
        # ---- Rooftop dining ----
        models.Bay(activity_type_id=dining.id, name="Standard Table", bay_tier="standard",
                   price_per_session=1500, max_players=6,
                   description="Open-air terrace by the bar & DJ",
                   image=IMG_DINING3),
        models.Bay(activity_type_id=dining.id, name="VIP Lounge", bay_tier="vip",
                   price_per_session=2500, max_players=6,
                   description="Tropical lounge with skyline views",
                   image=IMG_DINING),
        models.Bay(activity_type_id=dining.id, name="VVIP Skyline Table", bay_tier="vvip",
                   price_per_session=3500, max_players=8,
                   description="Secluded corner table with the best view in the house",
                   image=IMG_DINING2),
        # ---- Private screening ----
        models.Bay(activity_type_id=screening.id, name="Standard Lounge", bay_tier="standard",
                   price_per_session=1800, max_players=12,
                   description="Bean bags & sofas up front — great for groups",
                   image=IMG_SCREEN),
        models.Bay(activity_type_id=screening.id, name="VIP Recliners", bay_tier="vip",
                   price_per_session=2800, max_players=10,
                   description="Premium recliners, centre of the screen",
                   image=IMG_SCREEN),
        models.Bay(activity_type_id=screening.id, name="VVIP Couple Pods", bay_tier="vvip",
                   price_per_session=3500, max_players=2,
                   description="Private 2-seater pods with a side table",
                   image=IMG_SCREEN2),
    ])

    db.add_all([
        models.FoodItem(name="Classic Cheeseburger", price=290, category="Burgers",
                        description="Juicy beef patty, melted cheddar, lettuce, tomato, onion",
                        image="https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=400&q=80"),
        models.FoodItem(name="Spicy Jalapeno Burger", price=290, category="Burgers",
                        description="Beef patty, pepper jack cheese, jalapenos, chipotle mayo",
                        image="https://images.unsplash.com/photo-1550547660-d9450f859349?w=400&q=80"),
        models.FoodItem(name="BBQ Bacon Burger", price=290, category="Burgers",
                        description="Beef patty, crispy bacon, cheddar cheese, BBQ sauce",
                        image="https://images.unsplash.com/photo-1572802419224-296b0aeee0d9?w=400&q=80"),
        models.FoodItem(name="Cold Brew Coffee", price=180, category="Beverages",
                        description="Slow-steeped 18h, smooth and bold",
                        image="https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=400&q=80"),
        models.FoodItem(name="Molten Chocolate Cake", price=240, category="Desserts",
                        description="Warm gooey centre, vanilla bean ice cream",
                        image="https://images.unsplash.com/photo-1606313564200-e75d5e30476c?w=400&q=80"),
    ])
    db.commit()
