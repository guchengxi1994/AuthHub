FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir ".[web,redis]"

RUN useradd --create-home --uid 10001 authhub && mkdir -p /var/lib/authhub && chown -R authhub:authhub /app /var/lib/authhub
USER authhub

EXPOSE 8000

CMD ["uvicorn", "auth_hub.main:app", "--host", "0.0.0.0", "--port", "8000"]

