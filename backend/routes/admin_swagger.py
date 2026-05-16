"""Admin-only Swagger UI — serves consolidated OpenAPI specs for all Nivesh services.

Routes (all require admin session):
    GET /api/admin/swagger          — Swagger UI HTML (unified, multi-spec)
    GET /api/admin/openapi/app.yaml — Nivesh App OpenAPI 3.1 spec
    GET /api/admin/openapi/nidp.yaml — NIDP consolidated OpenAPI 3.1 spec
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pathlib import Path

from deps import require_admin

router = APIRouter()

_DOCS_DIR = Path(__file__).parent.parent / "docs"

_SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Nivesh API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f1117; color: #e2e8f0; }

    #topbar {
      display: flex; align-items: center; gap: 16px;
      padding: 12px 24px;
      background: #1a1d27;
      border-bottom: 1px solid #2d3148;
      position: sticky; top: 0; z-index: 100;
    }

    #topbar .logo {
      font-size: 18px; font-weight: 700; color: #7c6af7;
      letter-spacing: -0.3px;
    }

    #topbar .badge {
      font-size: 11px; background: #2d3148; color: #94a3b8;
      padding: 2px 8px; border-radius: 10px;
    }

    #topbar label { font-size: 13px; color: #94a3b8; margin-left: auto; }

    #api-selector {
      appearance: none;
      background: #252836;
      border: 1px solid #3d4263;
      color: #e2e8f0;
      font-size: 13px;
      padding: 6px 32px 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      outline: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2394a3b8' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 10px center;
    }
    #api-selector:focus { border-color: #7c6af7; }

    #swagger-ui { max-width: 1280px; margin: 0 auto; padding: 24px; }

    /* Override Swagger UI dark theme */
    .swagger-ui { filter: invert(0); }
    .swagger-ui .topbar { display: none !important; }
    .swagger-ui .info .title { color: #e2e8f0; }
    .swagger-ui .info .description p,
    .swagger-ui .info table { color: #94a3b8; }
    .swagger-ui .scheme-container { background: #1a1d27; border: 1px solid #2d3148; border-radius: 6px; }
    .swagger-ui .opblock-tag { color: #c4b5fd; border-color: #2d3148; }
    .swagger-ui .opblock { border-radius: 6px; margin: 4px 0; border: 1px solid #2d3148; }
    .swagger-ui .opblock .opblock-summary { border-radius: 5px; }
    .swagger-ui .opblock.opblock-get .opblock-summary { background: rgba(59,130,246,.08); }
    .swagger-ui .opblock.opblock-post .opblock-summary { background: rgba(34,197,94,.08); }
    .swagger-ui .opblock.opblock-put .opblock-summary { background: rgba(234,179,8,.08); }
    .swagger-ui .opblock.opblock-patch .opblock-summary { background: rgba(168,85,247,.08); }
    .swagger-ui .opblock.opblock-delete .opblock-summary { background: rgba(239,68,68,.08); }
    .swagger-ui section.models { border: 1px solid #2d3148; border-radius: 6px; }
    .swagger-ui .model-container { background: #1a1d27; }
    .swagger-ui select, .swagger-ui input { background: #252836; color: #e2e8f0; border-color: #3d4263; }
    .swagger-ui .btn { border-radius: 4px; }
    .swagger-ui .btn.authorize { background: #7c6af7; border-color: #7c6af7; color: #fff; }
    .swagger-ui .response-col_status { color: #e2e8f0; }
    .swagger-ui .response-col_description { color: #94a3b8; }
    .swagger-ui table thead tr td, .swagger-ui table thead tr th { color: #94a3b8; border-color: #2d3148; }
    .swagger-ui .parameter__name { color: #c4b5fd; }
    .swagger-ui .parameter__type { color: #7dd3fc; }
    .swagger-ui .markdown p, .swagger-ui .renderedMarkdown p { color: #94a3b8; }
    body .swagger-ui .wrapper, body .swagger-ui .info { background: transparent; }
    .swagger-ui .loading-container .loading:after { color: #7c6af7; }
  </style>
</head>
<body>
  <div id="topbar">
    <span class="logo">⚡ Nivesh API Docs</span>
    <span class="badge">Admin Only</span>
    <label for="api-selector">Spec:</label>
    <select id="api-selector" onchange="loadSpec(this.value)">
      <option value="/api/admin/openapi/app.yaml">Nivesh App API (242 ops)</option>
      <option value="/api/admin/openapi/nidp.yaml">NIDP — DaaS + Query API (114 ops)</option>
    </select>
  </div>
  <div id="swagger-ui"></div>

  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    let ui;

    function loadSpec(url) {
      if (ui) {
        ui = SwaggerUIBundle({
          url: url,
          dom_id: '#swagger-ui',
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
          layout: 'StandaloneLayout',
          deepLinking: true,
          displayRequestDuration: true,
          filter: true,
          withCredentials: true,
          requestInterceptor: (req) => {
            // Forward cookies so session auth works for the App API
            req.credentials = 'include';
            return req;
          },
          onComplete: () => {
            // Auto-populate API key for NIDP specs if stored in sessionStorage
            const savedKey = sessionStorage.getItem('nidp_api_key');
            if (savedKey && url.includes('nidp')) {
              ui.preauthorizeApiKey('ApiKeyAuth', savedKey);
            }
          },
        });
      }
    }

    window.onload = () => {
      ui = SwaggerUIBundle({
        url: '/api/admin/openapi/app.yaml',
        dom_id: '#swagger-ui',
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
        layout: 'StandaloneLayout',
        deepLinking: true,
        displayRequestDuration: true,
        filter: true,
        withCredentials: true,
        requestInterceptor: (req) => {
          req.credentials = 'include';
          return req;
        },
      });

      document.getElementById('api-selector').addEventListener('change', (e) => {
        ui = SwaggerUIBundle({
          url: e.target.value,
          dom_id: '#swagger-ui',
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
          layout: 'StandaloneLayout',
          deepLinking: true,
          displayRequestDuration: true,
          filter: true,
          withCredentials: true,
          requestInterceptor: (req) => {
            req.credentials = 'include';
            return req;
          },
          onComplete: () => {
            const savedKey = sessionStorage.getItem('nidp_api_key');
            if (savedKey && e.target.value.includes('nidp')) {
              ui.preauthorizeApiKey('ApiKeyAuth', savedKey);
            }
          },
        });
      });
    };
  </script>
</body>
</html>"""


_SWAGGER_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://unpkg.com 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://unpkg.com",
    "img-src 'self' data: https:",
    "font-src 'self' https://unpkg.com",
    "connect-src 'self' https:",
    "frame-ancestors 'none'",
])


@router.get("/api/admin/swagger", response_class=HTMLResponse, include_in_schema=False)
async def swagger_ui(_user: dict = Depends(require_admin)):
    """Unified Swagger UI for all Nivesh APIs. Admin session required."""
    response = HTMLResponse(_SWAGGER_HTML)
    # Set before middleware runs — middleware uses setdefault so this won't be overwritten.
    response.headers["Content-Security-Policy"] = _SWAGGER_CSP
    return response


@router.get("/api/admin/openapi/app.yaml", include_in_schema=False)
async def openapi_app_yaml(_user: dict = Depends(require_admin)):
    """Serve the Nivesh App OpenAPI 3.1 spec (YAML)."""
    path = _DOCS_DIR / "nivesh-app-openapi.yaml"
    return Response(path.read_text(), media_type="application/yaml")


@router.get("/api/admin/openapi/nidp.yaml", include_in_schema=False)
async def openapi_nidp_yaml(_user: dict = Depends(require_admin)):
    """Serve the NIDP consolidated OpenAPI 3.1 spec (YAML)."""
    path = _DOCS_DIR / "nidp-openapi.yaml"
    return Response(path.read_text(), media_type="application/yaml")
