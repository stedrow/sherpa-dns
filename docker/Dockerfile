FROM python:3.12-slim

WORKDIR /app

# Install dependencies
# Copy requirements from the project root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# Copy the sherpa_dns package into the /app directory
COPY ./sherpa_dns ./sherpa_dns

# Create non-root user for security and add to docker group
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m sherpa

# Expose ports for health check and metrics
EXPOSE 8080

# Create entrypoint script to handle Docker socket permissions
# Copy entrypoint script from the docker directory in the build context
COPY ./docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]

# Run the application using the ENV variable for the config path
CMD ["python", "-m", "sherpa_dns", "/config/sherpa-dns.yaml"]
