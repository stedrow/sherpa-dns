FROM python:3.13-slim

WORKDIR /app

# Install dependencies
# Copy requirements from the project root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./sherpa_dns ./sherpa_dns
# Copy the VERSION file
COPY VERSION .

# Create non-root user for security and add to docker group
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m sherpa

# Expose ports for health check and metrics
EXPOSE 8080

# Add entrypoint script
COPY ./docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]

# Run the application
CMD ["python", "-m", "sherpa_dns", "/config/sherpa-dns.yaml"]
