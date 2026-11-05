"""Nivesh Autonomous Trading Desk — a separate application that reuses the backend's code.

It runs as its own FastAPI service (`autodesk.main:app`), keeps its own records in the Postgres schema `autodesk`,
and has its own UI (built later from the owner's designs). It never writes to the existing paper-trading collections
and has no route to a broker: the only execution destinations are the paper and shadow adapters.

Specs: docs/prd/Nivesh_Autonomous_Trading_Desk_Complete_PRD_v2.0.md and
docs/prd/Nivesh_Autonomous_Trading_Desk_Technical_Architecture_v1.0.md. Design: docs/autodesk/DESIGN.md.
"""

APP_NAME = "nivesh-autodesk"
APP_VERSION = "0.1.0"
