FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        fluxbox \
        novnc \
        websockify \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    DATA_DIR=/data

VOLUME ["/data"]
EXPOSE 8099 7900

ENTRYPOINT ["/entrypoint.sh"]
