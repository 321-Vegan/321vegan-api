import sentry_sdk
from urllib.parse import urlencode
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

from app.routes import (
    auth_router,
    account_router,
    user_router,
    brand_router,
    product_router,
    cosmetic_router,
    additive_router,
    household_cleaner_router,
    apiclient_router,
    error_report_router,
    export_router,
    checking_router,
    scoring_router,
    healthcheck_router,
    product_category_router,
    interesting_product_router,
    scan_event_router,
    shop_router,
    partner_router,
    partner_category_router,
    subscription_router,
    webhook_router,
    product_not_found_report_router,
    product_found_report_router,
    shop_review_router,
    b12_intake_router,
    xp_router,
    avatar_router,
)
from app.log import get_logger

app = FastAPI(title="321Vegan API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost',
        'http://localhost:3000',
        'http://localhost:8080',
        "https://321vegan.fr",
        "https://www.321vegan.fr",
        "https://www.tool.321vegan.fr",
        "https://tool.321vegan.fr",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

log = get_logger(__name__)


@app.middleware("http")
async def flatten_query_string_lists(request: Request, call_next):
    """
    Middleware to turn comma-delimited query parameter strings 
    into repeated query parameters
    """
    flattened = []
    for key, value in request.query_params.multi_items():
        flattened.extend((key, entry) for entry in value.split(','))
    request.scope["query_string"] = urlencode(
        flattened, doseq=True).encode("utf-8")
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = {k: "***" if k == "password" else v for k, v in exc.body.items()} if isinstance(exc.body, dict) else exc.body
    log.error(f"Validation error: {exc.errors()}")
    log.error(f"Request body: {body}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": body},
    )

app.include_router(auth_router, prefix="/auth", tags=["authentication"])
app.include_router(account_router, prefix="/me", tags=["account"])
app.include_router(user_router, prefix="/users", tags=["user"])
app.include_router(brand_router, prefix="/brands", tags=["brand"])
app.include_router(product_router, prefix="/products", tags=["product"])
app.include_router(cosmetic_router, prefix="/cosmetics", tags=["cosmetic"])
app.include_router(additive_router, prefix="/additives", tags=["additive"])
app.include_router(household_cleaner_router,
                   prefix="/household-cleaners", tags=["household_cleaners"])
app.include_router(apiclient_router, prefix="/apiclients", tags=["apiclient"])
app.include_router(error_report_router,
                   prefix="/error-reports", tags=["error_report"])
app.include_router(export_router, prefix="/export", tags=["export"])
app.include_router(checking_router, prefix="/checkings", tags=["checking"])
app.include_router(scoring_router, prefix="/scoring", tags=["scoring"])
app.include_router(healthcheck_router,
                   prefix="/healthcheck", tags=["healthcheck"])
app.include_router(product_category_router,
                   prefix="/product-categories", tags=["product_category"])
app.include_router(interesting_product_router,
                   prefix="/interesting-products", tags=["interesting_product"])
app.include_router(scan_event_router, prefix="/scan-events",
                   tags=["scan_event"])
app.include_router(shop_router, prefix="/shops", tags=["shop"])
app.include_router(partner_router, prefix="/partners", tags=["partner"])
app.include_router(partner_category_router, prefix="/partner-categories", tags=["partner_category"])
app.include_router(subscription_router, prefix="/subscriptions", tags=["subscription"])
app.include_router(webhook_router, prefix="/webhooks", tags=["webhook"])
app.include_router(product_not_found_report_router, prefix="/product-not-found-reports", tags=["product_not_found_report"])
app.include_router(product_found_report_router, prefix="/product-found-reports", tags=["product_found_report"])
app.include_router(shop_review_router, prefix="/shop-reviews", tags=["shop_review"])
app.include_router(b12_intake_router, prefix="/b12-intakes", tags=["b12_intake"])
app.include_router(xp_router, prefix="/xp-actions", tags=["xp"])
app.include_router(avatar_router, prefix="/avatars", tags=["avatar"])

# Serve static files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
