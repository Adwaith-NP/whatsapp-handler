FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# libmagic1 -> required by python-magic (a neonize dependency)
# ca-certificates -> TLS to WhatsApp's servers
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8100
CMD ["python", "main.py"]
