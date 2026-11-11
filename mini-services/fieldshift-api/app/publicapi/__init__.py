"""Public API platform (P3 W6): API keys, key authentication, outgoing webhooks.

Modules:
- ``api_keys``  — key lifecycle service, hashing, scopes, per-key rate limiting
                  and the ``require_api_key`` FastAPI dependency.
- ``webhooks``  — endpoint CRUD, event emission (``emit_event``), HMAC-signed
                  delivery with exponential backoff, dead-lettering and the
                  retry sweep.
- ``emitters``  — stable import surface for domain services that emit events.

All service code is synchronous (``def`` + SQLAlchemy ``Session``), consistent
with the rest of the P3 backend.
"""
