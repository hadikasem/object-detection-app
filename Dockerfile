# 1) Small Python base image
FROM python:3.11-slim

# 2) Keep Python tidy
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 3) Workdir inside the container
WORKDIR /app

# 4) System deps (minimal set for OpenCV headless)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 5) Install PyTorch CPU wheels from the official index
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    torch torchvision torchaudio

# 6) Install the rest of your Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 7) Copy your app code (including models/, templates/, static/)
COPY . .

# 8) Expose the port your app listens on
EXPOSE 8080

# 9) Launch with gunicorn (2 worker threads for concurrency)
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:8080", "app:app"]
