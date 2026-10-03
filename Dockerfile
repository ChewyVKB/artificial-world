# Artificial World — one small container: the simulation + the web viewer.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aworld ./aworld
COPY web ./web
COPY config ./config
COPY tests ./tests

# Worlds are saved here (mapped to a folder on the VM by docker-compose).
VOLUME /app/data
EXPOSE 8080

CMD ["python", "-m", "aworld", "serve", "--data", "/app/data", "--port", "8080", "--autoplay"]
