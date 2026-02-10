FROM python:3.10-slim

# Install Node.js
RUN apt-get update && apt-get install -y curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean

WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your 1700 line script
COPY . .

# Create folders for your script logic
RUN mkdir -p upload_bots inf logs && chmod -R 777 /app

# Koyeb default port
EXPOSE 8080

CMD ["python", "main.py"]
