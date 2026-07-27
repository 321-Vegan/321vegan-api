from app.crud.user import user_crud
from app.crud.brand import brand_crud
from app.crud.product import product_crud
from app.crud.household_cleaner import household_cleaner_crud
from app.crud.additive import additive_crud
from app.crud.apiclient import apiclient_crud
from app.crud.error_reports import error_report_crud
from app.crud.checking import checking_crud
from app.crud.product_category import product_category_crud
from app.crud.interesting_product import interesting_product_crud
from app.crud.scan_event import scan_event_crud
from app.crud.partner import partner_crud
from app.crud.partner_category import partner_category_crud
from app.crud import scoring
from app.crud.subscription import subscription_crud
from app.crud.product_not_found_report import product_not_found_report_crud
from app.crud.shop_review import shop_review_crud
from app.crud.b12_intake import b12_intake_crud
from app.crud.xp import xp_action_type_crud, xp_event_crud

__all__ = [
    "user_crud",
    "brand_crud",
    "product_crud",
    "additive_crud",
    "household_cleaner_crud",
    "apiclient_crud",
    "error_report_crud",
    "checking_crud",
    "product_category_crud",
    "interesting_product_crud",
    "scan_event_crud",
    "partner_crud",
    "partner_category_crud",
    "scoring",
    "subscription_crud",
    "product_not_found_report_crud",
    "shop_review_crud",
    "b12_intake_crud",
    "xp_action_type_crud",
    "xp_event_crud",
]
