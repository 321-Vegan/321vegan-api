from app.models.user import User, Base
from app.models.brand import Brand
from app.models.product import Product
from app.models.apiclient import ApiClient
from app.models.cosmetic import Cosmetic
from app.models.error_report import ErrorReport
from app.models.checking import Checking
from app.models.scoring import Category, Criterion, BrandCriterionScore
from app.models.product_category import ProductCategory
from app.models.interesting_product import InterestingProduct, InterestingProductType
from app.models.scan_event import ScanEvent
from app.models.shop import Shop
from app.models.household_cleaner import HouseholdCleaner
from app.models.additive import Additive
from app.models.partner import Partner
from app.models.partner_category import PartnerCategory
from app.models.subscription import Subscription, SubscriptionEvent, SubscriptionPlatform, SubscriptionStatus, SubscriptionEventType
from app.models.product_not_found_report import ProductNotFoundReport
from app.models.product_found_report import ProductFoundReport
from app.models.shop_review import ShopReview, ShopReviewStatus
from app.models.b12_intake import B12Intake, B12IntakeFrequency
from app.models.xp import XPActionType, XPEvent
from app.models.avatar import Avatar, UserAvatar
