.PHONY: build run run-dev stop clean test lint format

# Docker image name
IMAGE_NAME = sherpa-dns

# Build the Docker image
build:
	docker build -t $(IMAGE_NAME):latest .

# Run the application in production mode
run: build
	docker-compose up -d

# Run the application in development mode (with logs)
run-dev: build
	docker-compose up

# Stop the application
stop:
	docker-compose down

# Clean up Docker resources
clean: stop
	docker rmi $(IMAGE_NAME):latest

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
	@echo "  make build     - Build the Docker image"
	@echo "  make run       - Run the application in production mode"
	@echo "  make run-dev   - Run the application in development mode (with logs)"
	@echo "  make stop      - Stop the application"
	@echo "  make clean     - Clean up Docker resources"
	@echo "  make lint      - Run linting checks"
	@echo "  make format    - Sort imports, apply lint fixes, and formatting"
	@echo "  make help      - Show this help message"
