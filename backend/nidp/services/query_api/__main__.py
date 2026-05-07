"""Cloud Run entry-point. Listens on $PORT (default 8080)."""
from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "nidp.services.query_api.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
