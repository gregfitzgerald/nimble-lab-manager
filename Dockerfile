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

FROM python:3.12-slim

# Run as a non-root user.
RUN useradd --create-home --uid 1000 nlm

WORKDIR /app

# Runtime dependencies (fastapi, uvicorn, python-multipart for uploads, segno for
# QR labels); everything else the app uses is Python stdlib. Dev/test deps
# (requirements-dev.txt) are intentionally NOT installed in the image.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + schema/seed + the synthetic data generator.
COPY app ./app
COPY web ./web
COPY schema.sql seed.sql generate_data.py ./

# Persistent-data mount point; lab.db is symlinked into it (see header note).
RUN mkdir -p /data \
    && ln -s /data/lab.db /app/lab.db \
    && chown -R nlm:nlm /app /data

USER nlm

VOLUME /data
EXPOSE 8770

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8770"]
