FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests
COPY requirements-dev.txt ./requirements-dev.txt
COPY entrypoint.sh ./entrypoint.sh
RUN chmod 0555 ./entrypoint.sh && chown -R app:app /srv/app

USER app
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
