FROM python:3.11-slim

# Install system dependencies
# We need Firefox and Geckodriver to run Selenium in headless mode
RUN apt-get update && apt-get install -y \
    firefox-esr \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Download and install Geckodriver
RUN GECKODRIVER_VERSION=$(wget -qO- "https://api.github.com/repos/mozilla/geckodriver/releases/latest" | grep -Po '"tag_name": "v\K[^"]*') && \
    wget -O /tmp/geckodriver.tar.gz "https://github.com/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz" && \
    tar -xzf /tmp/geckodriver.tar.gz -C /usr/local/bin/ && \
    chmod +x /usr/local/bin/geckodriver && \
    rm /tmp/geckodriver.tar.gz

# Set up working directory
WORKDIR /app

# Copy dependency requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose the API port
EXPOSE 8000

# Set environment variables for Selenium/Firefox
ENV MOZ_HEADLESS=1

# Start the FastAPI server
CMD ["python", "api.py"]
