import logging
import logging_loki
import uuid
import time
import os
from fastapi import FastAPI, Request
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


# ── Loki handler (direct push, like pino-loki) ───────────────────────
class LokiHandler(logging_loki.LokiHandler):
    """Adds X-Scope-OrgID multi-tenancy header to every push."""
    def emit(self, record):
        try:
            self.emitter.session.headers.update({"X-Scope-OrgID": "tenant1"})
        except Exception:
            pass
        super().emit(record)


stream_handler = logging.StreamHandler()

logger = logging.getLogger("fastapi-app")
logger.setLevel(logging.INFO)
logger.addHandler(stream_handler)

# Only push to Loki when running inside the cluster
if os.getenv("ENABLE_LOKI", "false").lower() == "true":
    loki_handler = LokiHandler(
        url=os.getenv("LOKI_URL", "http://loki:3100/loki/api/v1/push"),
        tags={"service": "fastapi-app", "env": "development"},
        version="1",
    )
    logger.addHandler(loki_handler)

logger.propagate = False


# ── App ──────────────────────────────────────────────────────────────
app = FastAPI()
if _PROM_AVAILABLE:
    Instrumentator().instrument(app).expose(app)


@app.middleware("http")
async def correlation_and_logging(request: Request, call_next):
    # Generate correlation ID per request (like correlationId.js)
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id

    # Set child logger BEFORE call_next so route handlers can access request.state.log
    child = logging.LoggerAdapter(logger, {"correlationId": correlation_id})
    request.state.log = child

    start = time.time()
    try:
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)
        response.headers["X-Correlation-ID"] = correlation_id
        child.info(f"request_completed {request.method} {request.url.path} {response.status_code} {duration_ms}ms")
        return response
    except Exception as exc:
        duration_ms = round((time.time() - start) * 1000, 2)
        child.error(f"request_error: {str(exc)} {request.method} {request.url.path} {duration_ms}ms")
        raise


@app.get("/")
def hello_world(request: Request):
    request.state.log.info("hello_world_called")
    return {"message": "Hello, World!"}


@app.get("/status")
def status(request: Request):
    request.state.log.info("status_checked")
    return {"status": "ok", "version": "1.0.0"}
