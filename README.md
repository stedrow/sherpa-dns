# Sherpa-DNS

Sherpa-DNS is a python application designed to create and manage DNS records for services defined in docker compose stacks or stand-alone docker containers via labels. It draws inspiration from the Kubernetes External-DNS project but is specifically tailored for docker environments.

## Features

- Monitor docker container start/stop actions and create corresponding DNS records in Cloudflare
- Support both CNAME and A record types
- Allow users to specify desired hostnames via labels
- Support TTL configuration via labels
- Provide a proxied/non-proxied option for Cloudflare DNS records
- Enable clean lifecycle management of DNS records
- Support automatic record cleanup when services are removed
- Delayed DNS record cleanup to handle temporary outages or restarts

## Requirements

- Docker / Docker Compose
- Cloudflare API token with DNS edit permissions

## Installation

### Using Docker Compose (recommended)

1.  **Download the compose file:** Download the `docker-compose.yml` file from the [`docker/` directory](https://github.com/stedrow/sherpa-dns/blob/main/docker/docker-compose.yml) of this repository.
2.  **Create `sherpa-dns.yaml`:** In the **same directory** where you saved `docker-compose.yml`, create your `sherpa-dns.yaml` configuration file (you can use `example_sherpa-dns.yaml` as a starting point).
3.  **Create `.env` file:** In the **same directory**, create an `.env` file with your Cloudflare API token and, if using encryption, your encryption key:
    ```bash
    # .env file contents
    CLOUDFLARE_API_TOKEN=your_api_token_here
    ENCRYPTION_KEY=your_secret_passphrase_here # Only needed if registry.encrypt=true
    ```
4.  **Run Docker Compose:** From the directory containing your `docker-compose.yml`, `sherpa-dns.yaml`, and `.env` file, run:
    ```bash
    docker compose -f docker-compose.yml up -d
    ```

### Using Docker stand-alone

1.  **Create `sherpa-dns.yaml`:** In the **same directory** where you saved `docker-compose.yml`, create your `sherpa-dns.yaml` configuration file (you can use `example_sherpa-dns.yaml` as a starting point).

2. Run the container:
   ```bash
   docker run -d \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v ./sherpa-dns.yaml:/config/sherpa-dns.yaml \
     -e CLOUDFLARE_API_TOKEN=your_api_token_here \
     -e ENCRYPTION_KEY=your_secret_passphrase_here \
     --name sherpa-dns \
     ghcr.io/stedrow/sherpa-dns:latest
   ```

## Configuration

Sherpa-DNS uses a YAML configuration file for its settings. The default configuration file is located at `example_sherpa-dns.yaml`.

### Configuration Options

```yaml
# Source configuration
source:
  label_prefix: "sherpa.dns"
  label_filter: ""

# Provider configuration
provider:
  name: "cloudflare"
  cloudflare:
    api_token: "${CLOUDFLARE_API_TOKEN}"
    proxied_by_default: false

# Registry configuration
registry:
  type: "txt"
  txt_prefix: "sherpa-dns-"
  txt_owner_id: "default"
  txt_wildcard_replacement: "*"
  encrypt: false
  # encryption_key: This is a user-provided secret passphrase used to derive the actual
  #                  encryption key for TXT records. It is NOT the raw key itself.
  #                  Generate a strong random string (e.g., openssl rand -base64 32)
  #                  and keep it secure.
  encryption_key: "${ENCRYPTION_KEY:-}" # Set to your secret passphrase

# Controller configuration
controller:
  interval: "1m"
  once: false
  dry_run: false
  cleanup_on_stop: true
  cleanup_delay: "15m"

# Domain filtering
domains:
  include:
    - "example.com"
    - "*.example.org"
  exclude:
    - "internal.example.com"

# Log configuration
logging:
  level: "info"
```

## Usage

### Docker Compose Labels

To create DNS records for your Docker Compose services, add the following labels to your services:

```yaml
services:
  webapp:
    image: nginx:latest
    labels:
      sherpa.dns/hostname: "app.example.com"
      sherpa.dns/ttl: "1"  # 1 == AUTO TTL
      sherpa.dns/target: "192.168.0.101"
      sherpa.dns/type: "A"
      sherpa.dns/proxied: "false"
```

### Label Schema

- `sherpa.dns/hostname`: The desired hostname for the service (e.g., `app.example.com`)
- `sherpa.dns/ttl`: TTL value for the DNS record (optional, default: provider default)
- `sherpa.dns/type`: Record type, either `A` or `CNAME` (optional, default: `A`)
- `sherpa.dns/target`: Target value for the DNS record (optional, default: container IP for A records or service name for CNAME)
- `sherpa.dns/proxied`: Whether the record should be proxied (optional, default: false)

## Development
Docker development is recommended, makefile commands can make this easier as well.

### Makefile Commands

- `make build`: Build the Docker image
- `make run`: Run the application in production mode
- `make run-dev`: Run the application in development mode (with logs)
- `make stop`: Stop the application
- `make clean`: Clean up Docker resources
- `make lint`: Run linting
- `make help`: Show help message

## License

This project is licensed under the MIT License - see the LICENSE file for details.
