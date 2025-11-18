FROM python:3.12-slim

# System dependencies (you already had most of these — kept only the actually needed ones)
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libmagic1 \
    ffmpeg \
    poppler-utils \
    ghostscript \
    imagemagick \
    libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first (better layer caching)
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

EXPOSE 8088

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]