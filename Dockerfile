FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e .

RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

CMD ["uvicorn", "commerceops.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
