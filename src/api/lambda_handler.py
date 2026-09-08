"""Lambda entry point. Adapts the FastAPI app to an API Gateway event.

    API Gateway ─▶ Mangum ─▶ FastAPI ─▶ the same app that runs locally

Mangum translates one shape into another: an API Gateway v2 event becomes an
ASGI scope, and the ASGI response becomes the Lambda return value. Nothing about
`src/api/main.py` changes — the deployed API is the API, not a variant of it.

`lifespan="off"` because FastAPI's startup and shutdown events do not map onto a
function that is frozen between invocations. Nothing here uses them, and leaving
them on means Mangum runs a startup sequence per cold start for no benefit.
"""

from mangum import Mangum

from src.api.main import app

handler = Mangum(app, lifespan="off")
