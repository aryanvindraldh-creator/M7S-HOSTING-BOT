FROM python:3.10-slim

# Install Node.js, NPM, and Sudo (required by your script's ensure_node_installed function)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    sudo \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Give the environment full permissions as your script tries to chmod folders
RUN chmod 777 /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the 1700 line script and other files
COPY . .

# Create the folders your script expects
RUN mkdir -p upload_bots inf logs && chmod -R 777 /app

# Koyeb uses port 8080 by default
EXPOSE 8080

CMD ["python", "main.py"]
