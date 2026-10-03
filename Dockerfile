# Artificial World — one small container: the simulation + the web viewer.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Artificial World" \
      org.opencontainers.image.description="A persistent simulated world where life, language and maybe civilization emerge."

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aworld ./aworld
COPY web ./web
COPY tests ./tests
# The default settings live inside the image. If the mounted config folder is
# empty, they're copied into it on first start so you have a file to edit.
COPY config ./config.defaults
RUN mkdir -p /app/config /app/data

# Worlds are saved here (mapped to a folder on the host by docker compose).
VOLUME /app/data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/status', timeout=4)"

CMD ["python", "-m", "aworld", "serve", "--data", "/app/data", "--port", "8080", "--autoplay"]
