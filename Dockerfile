# Nimble Lab Manager -- FastAPI + SQLite, buildless SPA.
#
# The SQLite database builds itself on first boot: app.server's startup hook
# calls init_db(), which runs schema.sql + seed.sql and seeds the demo users.
# The app writes the DB at /app/lab.db; that path is a symlink into /data so
# a volume mounted at /data makes the database persist. WITHOUT a volume,
# lab.db is ephemeral and is rebuilt from seed on every container start.
#
# POST /api/reset rebuilds the schema in place (drop + re-run schema/seed) via
# db.rebuild_db(), so it writes through the symlink and keeps the same file on
# the volume -- volume-backed persistence survives an in-app reset.
#
# Optional durability: set LITESTREAM_REPLICA_URL (+ object-store credentials) to
# stream lab.db to object storage continuously; the entrypoint restores from it
# on a fresh volume. Unset, the container runs the app plainly (see
# docker-entrypoint.sh + litestream.yml).

FROM python:3.12-slim

# Run as a non-root user.
RUN useradd --create-home --uid 1000 nlm

# Litestream (streaming SQLite backup). Only activates when configured at
# runtime; the binary is small and idle-cost-free otherwise.
ARG LITESTREAM_VERSION=0.3.13
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz /tmp/litestream.tar.gz
RUN tar -C /usr/local/bin -xzf /tmp/litestream.tar.gz litestream && rm /tmp/litestream.tar.gz

WORKDIR /app

# Runtime dependencies (fastapi, uvicorn, python-multipart for uploads, segno for
# QR labels); everything else the app uses is Python stdlib. Dev/test deps
# (requirements-dev.txt) are intentionally NOT installed in the image.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + schema/seed + the synthetic data generator + deploy glue.
COPY app ./app
COPY web ./web
COPY schema.sql seed.sql generate_data.py litestream.yml docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Persistent-data mount point; lab.db is symlinked into it (see header note).
RUN mkdir -p /data \
    && ln -s /data/lab.db /app/lab.db \
    && chown -R nlm:nlm /app /data

USER nlm

VOLUME /data
EXPOSE 8770

# Entrypoint runs the app directly by default, or under Litestream when
# LITESTREAM_REPLICA_URL is set. Behaviour with no Litestream env is identical
# to a plain `uvicorn app.server:app`.
ENTRYPOINT ["./docker-entrypoint.sh"]
