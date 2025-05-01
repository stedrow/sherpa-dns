"""
Main entry point for Sherpa-DNS.
"""

import asyncio
import logging
import sys
from pathlib import Path

from sherpa_dns.config.config import Config
from sherpa_dns.controller.controller import Controller
from sherpa_dns.provider.cloudflare import CloudflareProvider
from sherpa_dns.registry.txt_registry import TXTRegistry
from sherpa_dns.source.docker_container import DockerContainerSource
from sherpa_dns.utils.health import HealthCheckServer

# Define the path to the version file within the container
VERSION_FILE_PATH = Path("/app/VERSION")


async def main():
    """Main entry point running all components concurrently."""
    app_version = "unknown"
    try:
        if VERSION_FILE_PATH.is_file():
            app_version = VERSION_FILE_PATH.read_text().strip()
    except Exception as e:
        logging.warning(f"Could not read version file {VERSION_FILE_PATH}: {e}")

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("sherpa-dns")
    logger.info(f"Starting Sherpa-DNS v{app_version}")

    # Load configuration
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    config = Config.from_yaml(config_path)

    # Set log level from configuration
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)
    # Set httpx logger level to WARNING unless root is DEBUG
    httpx_log_level = logging.DEBUG if log_level == logging.DEBUG else logging.WARNING
    logging.getLogger("httpx").setLevel(httpx_log_level)

    # Initialize components
    source = DockerContainerSource(config.label_prefix, config.label_filter)
    provider = CloudflareProvider(
        config.cloudflare_api_token,
        domain_filter=config.domain_filter,
        exclude_domains=config.exclude_domains,
        proxied_by_default=config.cloudflare_proxied_by_default,
        dry_run=config.dry_run,
    )
    registry = TXTRegistry(
        provider,
        txt_prefix=config.txt_prefix,
        txt_owner_id=config.txt_owner_id,
        txt_wildcard_replacement=config.txt_wildcard_replacement,
        encrypt_txt=config.encrypt_txt,
        encryption_key=config.encryption_key,
    )
    controller = Controller(
        source,
        registry,
        provider,
        interval=config.interval,
        cleanup_delay=config.cleanup_delay,
        cleanup_on_stop=config.cleanup_on_stop,
    )

    # Start health check server
    health_server = HealthCheckServer()
    health_server.start()

    try:
        # Run tasks concurrently
        if config.once:
            # Run once and exit
            await controller.run_once()
        else:
            logger.debug(
                "Starting background tasks: Reconciliation Loop, Source Event Listener, Controller Event Watcher, Cleanup Tracker"
            )
            # Run continuously
            await asyncio.gather(
                controller.run_reconciliation_loop(),
                source.watch_events(),
                controller.watch_events(),
                controller.run_cleanup_tracker(),
            )
    finally:
        # Stop health check server
        health_server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down Sherpa-DNS")
        sys.exit(0)
