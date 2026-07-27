from app.routes.auth import router as auth_router
from app.routes.account import router as account_router
from app.routes.user import router as user_router
from app.routes.brand import router as brand_router
from app.routes.product import router as product_router
from app.routes.cosmetic import router as cosmetic_router
from app.routes.additive import router as additive_router
from app.routes.household_cleaner import router as household_cleaner_router
from app.routes.apiclient import router as apiclient_router
from app.routes.error_report import router as error_report_router
from app.routes.export import router as export_router
from app.routes.checking import router as checking_router
from app.routes.scoring import router as scoring_router
from app.routes.healthcheck import router as healthcheck_router
from app.routes.product_category import router as product_category_router
from app.routes.interesting_product import router as interesting_product_router
from app.routes.scan_event import router as scan_event_router
from app.routes.shop import router as shop_router
from app.routes.partner import router as partner_router
from app.routes.partner_category import router as partner_category_router
from app.routes.subscription import router as subscription_router
from app.routes.webhook import router as webhook_router
from app.routes.product_not_found_report import router as product_not_found_report_router
from app.routes.product_found_report import router as product_found_report_router
from app.routes.shop_review import router as shop_review_router
from app.routes.b12_intake import router as b12_intake_router
from app.routes.xp import router as xp_router


__all__ = [
    "auth_router",
    "account_router",
    "user_router",
    "brand_router",
    "product_router",
    "cosmetic_router",
    "additive_router",
    "household_cleaner_router",
    "apiclient_router",
    "error_report_router",
    "export_router",
    "checking_router",
    "scoring_router",
    "healthcheck_router",
    "product_category_router",
    "interesting_product_router",
    "scan_event_router",
    "shop_router",
    "partner_router",
    "partner_category_router",
    "subscription_router",
    "webhook_router",
    "product_not_found_report_router",
    "product_found_report_router",
    "shop_review_router",
    "b12_intake_router",
    "xp_router",
]
