#!/bin/bash
# Fix ownership of the /data volume (mounted by Fly as root) then drop to
# the non-root 'agent' user to run the app.
chown -R agent:agent /data 2>/dev/null || true
exec gosu agent python -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8765 \
    --workers 1 --log-level info
