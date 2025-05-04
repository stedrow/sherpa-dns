FROM cgr.dev/chainguard/python:latest-dev AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

# Copy and install dependencies in virtual environment
COPY requirements.txt .
RUN python -m venv /app/venv && pip install --no-cache-dir -r requirements.txt

# --- Final Stage ---
FROM cgr.dev/chainguard/python:latest

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /app/venv /app/venv

# Copy application code and VERSION file
COPY ./sherpa_dns ./sherpa_dns
COPY VERSION .

# Expose ports for health check and metrics
EXPOSE 8080

# Run the application as the entrypoint
ENTRYPOINT ["python", "-m", "sherpa_dns", "/config/sherpa-dns.yaml"]
