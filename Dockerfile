FROM python:3.12-slim

RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --create-home --home-dir /home/app --shell /bin/bash app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc g++ libxml2-dev libxslt1-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app src/ ./src/
COPY --chown=app:app static/ ./static/

USER app
EXPOSE 5000

CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "5000"]
