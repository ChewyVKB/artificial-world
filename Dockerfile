# Artificial World — one small container: the simulation + the web viewer.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Artificial World" \
      org.opencontainers.image.description="A persistent simulated world where life, language and maybe civilization emerge." \
      org.opencontainers.image.source="https://github.com/ChewyVKB/artificial-world"

# wget: for health checks · tzdata: so TZ=America/Chicago etc. works
RUN apt-get update \
 && apt-get install -y --no-install-recommends wget tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aworld ./aworld
COPY web ./web
COPY tests ./tests
# The default settings live inside the image. If the mounted config folder is
# empty, they're copied into it on first start so you have a file to edit.
COPY config ./config.defaults
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /app/config /app/data

ENV PUID=1000 PGID=1000 TZ=UTC PYTHONUNBUFFERED=1

# Worlds are saved here (mapped to a folder on the host by docker compose).
VOLUME /app/data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD ["python", "-m", "aworld", "serve", "--data", "/app/data", "--port", "8080", "--autoplay"]
