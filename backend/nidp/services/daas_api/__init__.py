"""NIDP DaaS API — public Data-as-a-Service surface.

Read-only HTTPS over the NIDP warehouse, gated by per-caller API keys
issued via `python -m nidp.cli daas-keygen ...`. This is the *external*
surface; nidp.services.query_api is the internal admin surface.
"""
