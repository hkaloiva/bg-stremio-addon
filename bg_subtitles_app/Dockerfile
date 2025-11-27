FROM python:3.12-slim

# Install curl, unrar, and libarchive-tools with non-free repo enabled
RUN set -eux; \
    echo "deb http://deb.debian.org/debian trixie main contrib non-free non-free-firmware" > /etc/apt/sources.list; \
    echo "deb http://deb.debian.org/debian-security trixie-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    echo "deb http://deb.debian.org/debian trixie-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl \
        unrar \
        libarchive-tools; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/src

EXPOSE 8080
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8080"]
