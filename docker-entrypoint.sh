#!/bin/sh
# Container entrypoint. Runs the app directly by default; when Litestream is
# configured (LITESTREAM_REPLICA_URL set), restores the database from the last
# replica if it is missing, then runs the app under `litestream replicate` so
# every write is streamed to object storage.
#
# Keeping Litestream opt-in means a plain `docker run` (no replica URL) behaves
# exactly as it did before this file existed.
set -e

APP="uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8770}"

if [ -n "${LITESTREAM_REPLICA_URL}" ]; then
    # Disaster recovery: if the volume is empty (new machine, lost disk), pull
    # the database back before starting. -if-replica-exists makes the very first
    # deploy (no replica yet) a no-op rather than an error.
    if [ ! -f /data/lab.db ]; then
        echo "litestream: restoring /data/lab.db from ${LITESTREAM_REPLICA_URL}"
        litestream restore -if-replica-exists -config /app/litestream.yml /data/lab.db || true
    fi
    echo "litestream: replicating /data/lab.db -> ${LITESTREAM_REPLICA_URL}"
    exec litestream replicate -config /app/litestream.yml -exec "${APP}"
fi

exec ${APP}
