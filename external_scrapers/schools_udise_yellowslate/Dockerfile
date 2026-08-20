FROM python:3.10-slim

# Install chromium browser and system dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up app directory
WORKDIR /app

# Upgrade pip and pre-install CPU version of PyTorch, headless OpenCV, pandas, pyarrow, and huggingface_hub
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir opencv-python-headless pandas pyarrow huggingface_hub

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all scraper code
COPY . .

# Environment variables for Render
ENV PORT=10000
ENV UDISE_HEADLESS=1
ENV UDISE_CHROME=/usr/bin/chromium
ENV UDISE_BROWSER_CONCURRENCY=3
ENV HF_TOKEN=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
ENV HF_REPO=herseiiii/udise-data

EXPOSE 10000

CMD ["python", "start_render.py"]
