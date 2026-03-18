FROM python:3.12-slim

# Install build deps for couchbase SDK + curl/unzip for cblite
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake g++ libssl-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir couchbase flask

# Copy application code
COPY . .

# Download and install cblite 2.8 for Linux (only 2.x has the logcat subcommand)
# Users can convert binary .cbllog files to text inside the container
RUN curl -L -o /tmp/cblite.tar.gz \
    "https://github.com/couchbaselabs/couchbase-mobile-tools/releases/download/cblite-2.8EE-alpha/cblite.tar.gz" \
    && tar -xzf /tmp/cblite.tar.gz -C /usr/local/ \
    && chmod +x /usr/local/bin/cblite \
    && ldconfig \
    && rm /tmp/cblite.tar.gz

# Create directory for log files
RUN mkdir -p /app/cbl_logs

EXPOSE 5099

# Default: run the dashboard (users can override to run cbl_log_reader.py first)
CMD ["python3", "app.py", "config.json"]
