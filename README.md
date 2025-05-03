# Sherpa-DNS

Sherpa-DNS is a python application designed to create and manage DNS records for services defined in docker compose stacks or stand-alone docker containers via labels. It draws inspiration from the Kubernetes External-DNS project but is specifically tailored for docker environments.

## Table of Contents

- [Installation](#installation)
  - [Using Docker Compose (Recommended)](#using-docker-compose-recommended)
  - [Using Docker Stand-alone](#using-docker-stand-alone)
- [Configuration (`sherpa-dns.yaml`)](#configuration-sherpa-dnsyaml)
  - [Global Settings](#global-settings)
  - [`source` Section](#source-section)
  - [`provider` Section](#provider-section)
  - [`registry` Section](#registry-section)
  - [`controller` Section](#controller-section)
  - [`domains` Section](#domains-section)
  - [`logging` Section](#logging-section)
- [Usage: Docker Labels](#usage-docker-labels)
  - [Label Schema](#label-schema)
  - [Examples](#examples)
- [How it Works](#how-it-works)
- [Development](#development)
- [License](#license)

## Installation

Sherpa-DNS runs as a Docker container and requires access to the Docker socket to monitor container events.

### Using Docker Compose (Recommended)

This method uses the pre-built image from GitHub Container Registry.

1.  **Download the compose file:** Download `docker-compose.yml` from the [docker/directory](https://github.com/stedrow/sherpa-dns/blob/main/docker/docker-compose.yml) of the Sherpa-DNS repository.
2.  **Create `sherpa-dns.yaml`:** In the **same directory** where you saved `docker-compose.yml`, create your `sherpa-dns.yaml` configuration file. You can copy [`example_sherpa-dns.yaml`](https://github.com/stedrow/sherpa-dns/blob/main/example_sherpa-dns.yaml) as a starting point and modify it.
3.  **Create `.env` file:** In the **same directory**, create an `.env` file with your Cloudflare API token and, optionally, your encryption key (if `registry.encrypt_txt` is `true` in your config):
    ```bash
    # .env file contents
    CLOUDFLARE_API_TOKEN=your_api_token_here
    ENCRYPTION_KEY=your_secret_passphrase_here # Only needed if registry.encrypt=true
    ```
4.  **Run Docker Compose:** From the directory containing your `docker-compose.yml`, `sherpa-dns.yaml`, and `.env` file, run:
    ```bash
    docker compose -f docker-compose.yml up -d
    ```

### Using Docker Stand-alone

This method also uses the pre-built image.

1.  **Create `sherpa-dns.yaml`:** Create your configuration file in a directory of your choice (e.g., `/etc/sherpa-dns/sherpa-dns.yaml`).
2.  **Run the container:** Adjust the volume path for your configuration file. Provide environment variables directly.
    ```bash
    docker run -d \
      --name sherpa-dns \
      --restart unless-stopped \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v /path/to/your/sherpa-dns.yaml:/config/sherpa-dns.yaml \
      -e CLOUDFLARE_API_TOKEN=your_api_token_here \
      -e ENCRYPTION_KEY=your_secret_passphrase_here `# Optional` \
      ghcr.io/stedrow/sherpa-dns:latest
    ```

## Configuration (`sherpa-dns.yaml`)

Sherpa-DNS uses a YAML file (default: `sherpa-dns.yaml` passed as an argument, or looked for at `/config/sherpa-dns.yaml` inside the container) for configuration. Environment variables like `${VAR_NAME}` can be used and will be substituted from the container's environment (e.g., passed via `.env` or `-e`).

### `source` Section

Configures how Sherpa-DNS discovers target endpoints.

*   `label_prefix` (string): The prefix for Docker labels used by Sherpa-DNS.
    *   Default: `"sherpa.dns"`
*   `label_filter` (string, optional): If set, Sherpa-DNS will only process containers that have a specific label matching this filter.
    *   Format: Can be just a key (e.g., `"enable-sherpa"`) to check for the label's existence, or key=value (e.g., `"enable-sherpa=true"`) to check for a specific key and value.
    *   Default: `""` (empty string, meaning no filtering - process all containers).

### `provider` Section

Configures the DNS provider where records will be managed.

*   `name` (string): The name of the DNS provider.
    *   Default: `"cloudflare"` (Currently the only supported provider).
*   `cloudflare`: A nested section containing Cloudflare-specific settings.
    *   `api_token` (string): Your Cloudflare API token. **Required**. Use environment variable substitution (e.g., `"${CLOUDFLARE_API_TOKEN}"`).
    *   `proxied_by_default` (boolean): Sets the default "Proxied" status for created A/CNAME records if not specified by a label.
        *   Default: `false`

### `registry` Section

Configures how Sherpa-DNS tracks the DNS records it manages.

*   `type` (string): The type of registry to use.
    *   Default: `"txt"` (Currently the only supported type, uses TXT records for tracking).
*   `txt_prefix` (string): A prefix added to the hostname when creating the corresponding TXT registry record. This helps identify Sherpa-managed TXT records and avoids conflicts (e.g., a TXT and CNAME cannot have the same name).
    *   Default: `"sherpa-dns-"`
*   `txt_owner_id` (string): An identifier written into the TXT record content (`owner=...`) to distinguish records managed by different Sherpa-DNS instances (e.g., staging vs. production).
    *   Default: `"default"`
*   `txt_wildcard_replacement` (string): A string used to replace the literal `*` character in a hostname when generating the TXT record's *name*. This ensures the TXT record name itself is valid DNS syntax (e.g., `*.example.com` becomes `sherpa-dns-star.example.com` if the replacement is `star`).
    *   Default: `"star"`
*   `encrypt_txt` (boolean): Whether to encrypt the content of the TXT registry records.
    *   Default: `false`
*   `encryption_key` (string, optional): A **secret passphrase** used to derive the encryption key if `encrypt_txt` is `true`. **Do not use the raw encryption key here.** Use environment variable substitution (e.g., `"${ENCRYPTION_KEY}"`). Required if `encrypt_txt` is `true`.

### `controller` Section

Configures the main reconciliation logic.

*   `interval` (string): How often the controller reconciles the desired state (from Docker labels) with the actual state (from DNS provider). Uses duration format (e.g., `60s`, `1m`, `5m`).
    *   Default: `"1m"`
*   `once` (boolean): If `true`, run the reconciliation loop only once and then exit. Useful for testing or specific scripting scenarios.
    *   Default: `false`
*   `dry_run` (boolean): If `true`, calculate changes but do not actually make any calls to the DNS provider API. Logs planned changes instead.
    *   Default: `false`
*   `cleanup_on_stop` (boolean): If `true`, DNS records for containers that stop/disappear will be queued for deletion after a delay. If `false`, records are left behind.
    *   Default: `true`
*   `cleanup_delay` (string): How long to wait after a container stops before deleting its DNS records. Uses duration format (e.g., `30s`, `15m`, `1h`). Only relevant if `cleanup_on_stop` is `true`.
    *   Default: `"15m"`

### `domains` Section

Filters which DNS zones the provider should manage.

*   `include` (list of strings, optional): Only manage zones matching these domain names/patterns. Patterns can include wildcards (`*`). If empty or omitted, all zones accessible by the API token are potentially managed (subject to `exclude`).
*   `exclude` (list of strings, optional): Explicitly exclude zones matching these domain names/patterns. Exclusions take precedence over inclusions.

### `logging` Section

Configures application logging.

*   `level` (string): The minimum log level to output. Standard Python levels (e.g., `"debug"`, `"info"`, `"warning"`, `"error"`).
    *   Default: `"info"`

## Usage: Docker Labels

You control which DNS records Sherpa-DNS creates by adding labels to your Docker containers (either directly in `docker run` or within the `labels:` section of a `docker-compose.yml` service).

### Label Schema

Use the prefix defined in `source.label_prefix` (default `sherpa.dns`).

*   **`sherpa.dns/hostname` (string): Required.** The fully qualified domain name (FQDN) for the DNS record (e.g., `myapp.example.com`, `*.internal.example.com`).
*   **`sherpa.dns/type` (string): Optional.** The type of DNS record to create.
    *   Values: `"A"`, `"CNAME"`
    *   Default: `"A"`
*   **`sherpa.dns/target` (string): Optional.** The target/value of the DNS record.
    *   Default for `A` records: The IP address of the container within the default Docker bridge network (or a specific network if networking is configured differently - *check source code for exact logic*).
    *   Default for `CNAME` records: The container's name.
    *   You can override this to point an `A` record to a specific IP or a `CNAME` to a specific target hostname.
*   **`sherpa.dns/ttl` (string): Optional.** The Time-To-Live for the DNS record in seconds.
    *   Value: A number representing seconds (e.g., `"300"` for 5 minutes) OR the special value `"1"` which maps to Cloudflare's "Auto" TTL.
    *   Default: Cloudflare's default TTL (usually "Auto" / 1).
*   **`sherpa.dns/proxied` (string): Optional.** Whether the DNS record should be proxied through Cloudflare (orange cloud).
    *   Values: `"true"`, `"false"`
    *   Default: The value of `provider.cloudflare.proxied_by_default` in `sherpa-dns.yaml` (which defaults to `false`).

### Examples

**A Record for a Web App (Auto IP, Auto TTL, Not Proxied):**

```yaml
# docker-compose.yml
services:
  my-web-app:
    image: nginx:latest
    labels:
      - "sherpa.dns/hostname=app.example.com"
```

**A Record with Specific IP and TTL (Proxied):**

```yaml
# docker-compose.yml
services:
  backend-service:
    image: mybackend:latest
    labels:
      - "sherpa.dns/hostname=api.example.com"
      - "sherpa.dns/target=10.0.5.20"
      - "sherpa.dns/ttl=600"
      - "sherpa.dns/proxied=true"
```

**CNAME Record:**

```yaml
# docker-compose.yml
services:
  redirector:
    image: traefik/whoami # Example service
    labels:
      - "sherpa.dns/hostname=old-app.example.com"
      - "sherpa.dns/type=CNAME"
      - "sherpa.dns/target=new-app.example.com" # Point to another DNS name
      - "sherpa.dns/ttl=1" # Auto TTL
```

**Wildcard Record:**

```yaml
# docker-compose.yml
services:
  wildcard-handler:
    image: my-ingress:latest
    labels:
      - "sherpa.dns/hostname=*.internal.example.com"
      - "sherpa.dns/target=192.168.1.100" # Target IP for the wildcard A record
      - "sherpa.dns/type=A"
```

## How it Works

Sherpa-DNS operates with a few key components:

1.  **Source (`DockerContainerSource`):** Watches the Docker daemon for container events (start, stop, die) and periodically lists running containers. It extracts DNS configuration from container labels that match the configured prefix and filter.
2.  **Registry (`TXTRegistry`):** Queries the DNS Provider (Cloudflare) for special TXT records that act as a database. It uses these TXT records (identified by `txt_prefix` and `txt_owner_id`) to determine which A/CNAME records it currently manages.
3.  **Provider (`CloudflareProvider`):** Interacts with the Cloudflare API to list zones, list existing DNS records, create new records, update records, and delete records.
4.  **Controller (`Controller`):** The central coordinator. It periodically:
    *   Gets the *desired* state (list of `Endpoint` objects) from the Source.
    *   Gets the *current* state (list of managed `Endpoint` objects) from the Registry.
    *   Calculates the *changes* needed (create, update, delete) using the `Plan`.
    *   Tells the Registry to `sync` the changes, which involves calls to the Provider API to modify A/CNAME records *and* the corresponding TXT registry records.
    *   Manages a delayed cleanup mechanism for records associated with stopped containers.
5.  **Health Server (`HealthCheckServer`):** Provides basic `/health` and `/metrics` endpoints for monitoring.

## Development

If you want to contribute or run the code locally for development:

1.  Clone the repository.
2.  Create your `.env` and `sherpa-dns.yaml` files.
3.  Use the provided `Makefile`:
    *   `make format`: Format code using `isort`, `ruff`, `black`.
    *   `make lint`: Check code style using `ruff` and `black`.
    *   `make run-dev`: Build the image locally and run the container with logs attached, using `docker/docker-compose.dev.yml`. This forces a rebuild on each run.
    *   `make stop`: Stop any running `make run-dev` or `make run` containers.
    *   `make help`: Display available commands.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
