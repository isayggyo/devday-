from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def install_error_handlers(app):
    @app.middleware("http")
    async def request_identifier(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
        return JSONResponse({"detail": {
            "code": detail.get("code", f"HTTP_{error.status_code}"),
            "message": detail.get("message", "Feature not implemented" if error.status_code == 501 else "Request failed"),
            "requestId": getattr(request.state, "request_id", None),
            **{key: value for key, value in detail.items() if key not in {"code", "message"}},
        }}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse({"detail": {
            "code": "VALIDATION_ERROR", "message": "Invalid request",
            "requestId": getattr(request.state, "request_id", None),
            "fields": [{"location": list(item["loc"]), "type": item["type"], "message": item["msg"]} for item in error.errors()],
        }}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        return JSONResponse({"detail": {
            "code": "INTERNAL_ERROR", "message": "The request could not be completed",
            "requestId": getattr(request.state, "request_id", None),
        }}, status_code=500)
