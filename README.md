# Sherpa-DNS

Sherpa-DNS is a Python application designed to create and manage DNS records for services defined in Docker Compose files. It draws inspiration from the Kubernetes External-DNS project but is specifically tailored for Docker Compose environments.

## Features

- Monitor Docker Compose services and create corresponding DNS records in Cloudflare
- Support both CNAME and A record types
- Allow users to specify desired hostnames via labels
- Support TTL configuration via labels
- Provide a proxied/non-proxied option for Cloudflare DNS records
- Enable clean lifecycle management of DNS records
- Support automatic record cleanup when services are removed
- Delayed DNS record cleanup to handle temporary outages or restarts

## Requirements

- Python 3.12 or higher
- Docker
- Docker Compose
- Cloudflare API token with DNS edit permissions

## Installation

### Using Docker Compose

1. Clone the repository:
   ```bash
   git clone https://github.com/stedrow/sherpa-dns.git
   cd sherpa-dns
   ```

2. Configure your Cloudflare API token:
   ```bash
   # Create your .env file
   vim .env

   CLOUDFLARE_API_TOKEN="<your-api-token-with-dns-edit-perms>"
   ENCRYPTION_KEY="random-passphrase-here"  # optional: if encryption is enabled in your sherpa-dns.yaml
   ```
3. copy `example_sherpa-dns.yaml` -> `sherpa-dns.yaml` and edit as needed.   

4. Build and run the application:
   ```bash
   make run
   ```

### Using Docker

1. Build the Docker image:
   ```bash
   docker build -t sherpa-dns:latest .
   ```

2. Run the container:
   ```bash
   docker run -d \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v ./sherpa-dns.yaml:/config/sherpa-dns.yaml \
     -e CLOUDFLARE_API_TOKEN=your_api_token_here \
     --name sherpa-dns \
     sherpa-dns:latest
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
- `make run-local`: Run the application locally (without Docker)
- `make help`: Show help message

## License

This project is licensed under the MIT License - see the LICENSE file for details.
