FROM python:3.10-slim

# Install chromium browser and driver
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set up app directory
WORKDIR /app

# Pre-install CPU version of PyTorch and headless OpenCV to keep docker image size minimal (EasyOCR dependencies)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir opencv-python-headless

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install huggingface_hub for dataset persistence
RUN pip install --no-cache-dir huggingface_hub

# Copy all scraper code
COPY . .

# Configure scraper for headless chromium inside Docker
ENV PORT=7860
ENV UDISE_HEADLESS=1
ENV UDISE_CHROME=/usr/bin/chromium

EXPOSE 7860

CMD ["python", "app_hf.py"]
