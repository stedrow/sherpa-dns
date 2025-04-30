.PHONY: build run run-dev stop clean test lint format help

# Docker image name
IMAGE_NAME = sherpa-dns
# Compose files
COMPOSE_FILE = docker/docker-compose.yml
COMPOSE_DEV_FILE = docker/docker-compose.dev.yml
# Dockerfile location
DOCKERFILE = docker/Dockerfile

# Build the Docker image
build:
	docker build -t $(IMAGE_NAME):latest -f $(DOCKERFILE) .

# Run the application in production mode (uses pre-built image from docker-compose.yml)
run:
	# Note: This command uses the image specified in $(COMPOSE_FILE)
	# Ensure the image ghcr.io/stedrow/sherpa-dns:<tag> exists and the config is present
	docker compose --env-file .env -f $(COMPOSE_FILE) up -d

# Run the application in development mode (builds locally, with logs)
run-dev:
	# This command builds the image locally using $(COMPOSE_DEV_FILE)
	# --env-file .env ensures environment variables are loaded from the project root
	# --build forces a rebuild of the image
	docker compose --env-file .env -f $(COMPOSE_DEV_FILE) up --build

# Stop the running application (stops services defined in either compose file)
stop:
	# Attempts to stop services defined in both compose files, ignoring errors if one isn't running
	-docker compose -f $(COMPOSE_FILE) down
	-docker compose -f $(COMPOSE_DEV_FILE) down

# Clean up Docker resources (removes locally built image)
clean: stop
	docker rmi $(IMAGE_NAME):latest || true # Ignore error if image doesn't exist

# Run linting
lint:
	ruff check .
	black --check sherpa_dns

# Run formatting and apply fixes
format:
	isort sherpa_dns
	ruff check --fix .
	black sherpa_dns

# Show help
help:
	@echo "Available commands:"
	@echo "  make build     - Build the local Docker image using $(DOCKERFILE)"
	@echo "  make run       - Run production app using pre-built image defined in $(COMPOSE_FILE)"
	@echo "  make run-dev   - Build locally and run dev app using $(COMPOSE_DEV_FILE) (loads .env)"
	@echo "  make stop      - Stop running application containers (prod or dev)"
	@echo "  make clean     - Stop containers and remove the locally built Docker image ($(IMAGE_NAME):latest)"
	@echo "  make lint      - Run linting checks"
	@echo "  make format    - Sort imports, apply lint fixes, and formatting"
	@echo "  make help      - Show this help message"
