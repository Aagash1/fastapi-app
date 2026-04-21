import logging
import logging_loki
import uuid
import time
import os
from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator


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

logger = logging.getLogger("fastapi-orders")
logger.setLevel(logging.INFO)
logger.addHandler(stream_handler)

# Only push to Loki when running inside the cluster
if os.getenv("ENABLE_LOKI", "false").lower() == "true":
    loki_handler = LokiHandler(
        url=os.getenv("LOKI_URL", "http://loki:3100/loki/api/v1/push"),
        tags={"service": "fastapi-orders", "env": "development"},
        version="1",
    )
    logger.addHandler(loki_handler)

logger.propagate = False


# ── App ──────────────────────────────────────────────────────────────
app = FastAPI()
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


from fastapi import Body
from fastapi.responses import JSONResponse


@app.get("/orders")
def list_orders(request: Request):
    request.state.log.info("list_orders_called")
    return {"orders": [{"id": "ord_001", "customer": "Alice", "status": "DELIVERED"}, {"id": "ord_002", "customer": "Bob", "status": "SHIPPED"}]}


@app.get("/orders/{order_id}")
def get_order(order_id: str, request: Request):
    request.state.log.info(f"order_fetched orderId={order_id}")
    return {"id": order_id, "customer": "Alice", "items": ["laptop", "mouse"], "status": "DELIVERED"}
