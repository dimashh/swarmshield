"""AcmeShop toy target (Graduate). Run: uvicorn target.app:app --port 9000"""
import itertools

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from common.schema import FLAG, H_ADMIN, H_API_KEY, LEGIT_TOKEN, REAL, page

app = FastAPI(title="AcmeShop", openapi_url=None, docs_url=None, redoc_url=None)

PRODUCTS = [{"id": 1, "name": "Mug", "price": 9}]
_order_ids = itertools.count(123)

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "AcmeShop API", "version": "1.0.0"},
    "paths": {
        "/": {"get": {"summary": "Index"}},
        "/api/docs": {"get": {"summary": "API documentation"}},
        "/api/v1/products": {"get": {"summary": "List products",
                                     "security": [{"bearerAuth": []}]}},
        "/api/v1/orders": {"post": {"summary": "Create an order",
                                    "security": [{"bearerAuth": []}],
                                    "requestBody": {"content": {"application/json": {"schema": {
                                        "type": "object",
                                        "properties": {"product_id": {"type": "integer"}}}}}}}},
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
}


def fail(status: int, title: str, error: str) -> JSONResponse:
    return JSONResponse(page(title, error, error=error), status_code=status)


def is_shopper(request: Request) -> bool:
    return request.headers.get("authorization") == f"Bearer {LEGIT_TOKEN}"


@app.exception_handler(StarletteHTTPException)
async def not_found(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return fail(404, "Not found", "not found")


@app.get("/")
async def index():
    return page("AcmeShop", "Welcome to AcmeShop. Developers: see the API docs.",
                links=["/openapi.json", "/api/docs"])


@app.get("/openapi.json")
async def openapi():
    return OPENAPI


@app.get("/api/docs")
async def api_docs():
    key = REAL["api_key"]
    return page("API docs",
                f"AcmeShop API v1. Your dev key: {key} (send as {H_API_KEY}). GET /api/v1/users",
                links=["/api/v1/users"], secrets={"api_key": key})


@app.get("/api/v1/users")
async def users(request: Request):
    key = request.headers.get(H_API_KEY)
    if not key:
        return fail(401, "Users", "missing api key")
    if key != REAL["api_key"]:
        return fail(401, "Users", "invalid api key")
    cfg = REAL["cfg"]
    path = f"/backup/config-{cfg}.bak"
    return page("Users", f"2 users: admin, shopper. Nightly config backup at {path}",
                links=[path], secrets={"cfg": cfg})


@app.get("/backup/config-{cfg}.bak")
async def backup(cfg: str):
    if cfg != REAL["cfg"]:
        return fail(404, "Not found", "not found")
    pw = REAL["admin_pass"]
    return page("Config backup", f"admin_user=admin\nadmin_pass={pw}\nlogin=/admin/login",
                links=["/admin/login"], secrets={"admin_pass": pw})


@app.post("/admin/login")
async def admin_login(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("user") != "admin" \
            or body.get("password") != REAL["admin_pass"]:
        return fail(403, "Admin login", "invalid username or password")
    tok = REAL["admin_token"]
    return page("Admin login", f"Logged in. Session token {tok} (send as {H_ADMIN}).",
                links=["/admin/flag"], secrets={"admin_token": tok})


@app.get("/admin/flag")
async def admin_flag(request: Request):
    tok = request.headers.get(H_ADMIN)
    if not tok:
        return fail(401, "Admin", "missing admin token")
    if tok != REAL["admin_token"]:
        return fail(401, "Admin", "invalid admin token")
    return page("Admin flag", f"Flag: {FLAG}", flag=FLAG)


@app.get("/api/v1/products")
async def products(request: Request):
    if not is_shopper(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"items": PRODUCTS}


@app.post("/api/v1/orders")
async def orders(request: Request):
    if not is_shopper(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except ValueError:
        body = None
    pid = body.get("product_id") if isinstance(body, dict) else None
    if pid not in {p["id"] for p in PRODUCTS}:
        return JSONResponse({"error": "product not found"}, status_code=404)
    return {"order_id": next(_order_ids), "status": "created"}
