# The image a customer's Railway service pulls.
#
# Customers deploy this rather than the source repository. They get every
# release; they never get the code. Their Railway pulls ghcr.io/<owner>/<repo>
# with a read-only token — see NEW_CUSTOMER_SETUP.md.
#
# Built by .github/workflows/publish-image.yml on every release tag. There is no
# reason to build it by hand.
FROM python:3.12-slim

# tzdata so the business timezone resolves — the whole app dates things in the
# owner's local time, and a container with no zone info silently falls back to
# UTC, which is the bug we just spent an evening fixing on the calendar.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is cached unless requirements.txt changes, so
# an ordinary release rebuilds in seconds rather than minutes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Which build this is. There is no .git in the image, so it is stamped in at
# build time and read by branding.version().
ARG RELEASE_SHA=""
ARG RELEASE_TAG=""
ENV RELEASE_SHA=${RELEASE_SHA} \
    RELEASE_TAG=${RELEASE_TAG}

# Railway sets PORT. The default keeps `docker run -p 8080:8080` working for
# anyone poking at the image locally.
ENV PORT=8080
EXPOSE 8080

# Same command as railway.toml, so an image deploy and a source deploy run the
# application identically.
CMD ["sh", "-c", "gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT"]
