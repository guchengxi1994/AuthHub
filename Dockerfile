FROM python:3.13-slim

ARG AUTH_HUB_RELEASE=0.2.0
ARG AUTH_HUB_BUILD=container

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    AUTH_HUB_RELEASE=${AUTH_HUB_RELEASE} \
    AUTH_HUB_BUILD=${AUTH_HUB_BUILD}

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY sdk ./sdk

RUN pip install --no-cache-dir ".[web,redis]" "psycopg[binary]>=3.2" ./sdk

RUN useradd --create-home --uid 10001 authhub && mkdir -p /var/lib/authhub && chown -R authhub:authhub /app /var/lib/authhub
USER authhub

EXPOSE 8000

CMD ["uvicorn", "auth_hub.main:app", "--host", "0.0.0.0", "--port", "8000"]
