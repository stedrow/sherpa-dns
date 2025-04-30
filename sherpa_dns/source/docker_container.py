"""
Docker container source module for Sherpa-DNS.

This module is responsible for fetching metadata from Docker containers and
extracting DNS configuration from labels.
"""

import asyncio
import concurrent.futures
import ipaddress
import logging
from typing import Dict, List, Optional, Set

import docker
from docker.models.containers import Container

from sherpa_dns.models.models import Endpoint


class DockerContainerSource:
    """
    Source that fetches metadata from Docker containers.
    """

    def __init__(
        self, label_prefix: str = "sherpa.dns", label_filter: Optional[str] = None
    ):
        """
        Initialize a DockerContainerSource.

        Args:
            label_prefix: Prefix for DNS labels
            label_filter: Filter for container labels
        """
        self.label_prefix = label_prefix
        self.label_filter = label_filter
        self.logger = logging.getLogger("sherpa-dns.source.docker")
        self.event_queue = asyncio.Queue()

        # Initialize Docker client with explicit configuration
        try:
            self.docker_client = docker.from_env()
            # Test connection
            self.docker_client.ping()
            self.logger.debug("Successfully connected to Docker daemon")
        except docker.errors.DockerException as e:
            self.logger.error(f"Error connecting to Docker daemon: {e}")
            # Try with explicit socket path
            try:
                self.logger.debug("Trying to connect with explicit socket path")
                self.docker_client = docker.DockerClient(
                    base_url="unix://var/run/docker.sock"
                )
                self.docker_client.ping()
                self.logger.debug(
                    "Successfully connected to Docker daemon with explicit socket path"
                )
            except docker.errors.DockerException as inner_e:
                self.logger.error(
                    f"Error connecting to Docker daemon with explicit socket path: {inner_e}"
                )
                # Initialize with None and retry later
                self.docker_client = None

    async def endpoints(self) -> List[Endpoint]:
        """
        Returns a list of endpoint objects representing desired DNS records
        based on running containers with appropriate labels.

        Returns:
            List[Endpoint]: List of endpoints
        """
        endpoints = []

        # Try to reconnect if docker_client is None
        if self.docker_client is None:
            if not await self._reconnect_docker_client():
                return []  # Failed to reconnect

        try:
            # Get all running containers
            # Note: This list call is synchronous, potentially blocking. Consider executor if becomes an issue.
            containers = self.docker_client.containers.list(
                filters={"status": "running"}
            )

            for container in containers:
                # Filter containers by labels if filter is specified
                if self.label_filter and not self._matches_filter(
                    container.labels, self.label_filter
                ):
                    continue

                # Extract DNS configuration from labels
                container_endpoints = self._endpoints_from_container(container)
                endpoints.extend(container_endpoints)

            return endpoints
        except docker.errors.DockerException as e:
            self.logger.error(f"Error fetching containers: {e}")
            return []

    async def _reconnect_docker_client(self) -> bool:
        """Attempts to reconnect the docker client. Returns True on success, False otherwise."""
        if self.docker_client is not None:
            return True  # Already connected

        self.logger.info("Attempting to reconnect to Docker daemon")
        try:
            # Try default first
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            self.logger.debug("Successfully reconnected to Docker daemon (default)")
            return True
        except docker.errors.DockerException:
            self.logger.warning(
                "Failed reconnecting with default, trying explicit socket path"
            )
            try:
                # Try explicit path
                self.docker_client = docker.DockerClient(
                    base_url="unix://var/run/docker.sock"
                )
                self.docker_client.ping()
                self.logger.debug(
                    "Successfully reconnected to Docker daemon with explicit socket path"
                )
                return True
            except docker.errors.DockerException as e:
                self.logger.error(
                    f"Error reconnecting to Docker daemon with explicit socket path: {e}"
                )
                self.docker_client = None  # Ensure it's None on failure
                return False

    def _blocking_event_listener(self, loop: asyncio.AbstractEventLoop):
        """
        Runs in a separate thread to listen for Docker events.
        This method should not be async as it runs in an executor thread.
        """
        try:
            if self.docker_client is None:
                self.logger.error(
                    "Event listener thread: Docker client is None. Cannot start."
                )
                return

            self.logger.debug("Event listener thread polling Docker API for events.")
            # Note: events() is blocking when iterated
            events = self.docker_client.events(
                decode=True, filters={"type": "container"}
            )
            for event in events:
                event_type = event.get("status")
                if event_type in [
                    "start",
                    "die",
                    "stop",
                    "kill",
                    "pause",
                    "unpause",
                ]:  # Added more events just in case
                    # Put event onto the asyncio queue from the thread
                    future = asyncio.run_coroutine_threadsafe(
                        self.event_queue.put(event), loop
                    )
                    try:
                        # Wait briefly for the put to complete to avoid overwhelming queue on burst
                        future.result(timeout=5)
                        self.logger.debug(
                            f"Event listener thread: Queued event {event_type} - {event.get('id', '')[:12]}"
                        )
                    except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
                        self.logger.warning(
                            "Event listener thread: Timeout waiting for event queue put."
                        )
                    except Exception as e:
                        # Catch specific exceptions if possible, e.g., queue full?
                        self.logger.error(
                            f"Event listener thread: Error getting result from queue put: {e}"
                        )
                else:
                    # Log other events at debug level if needed
                    # self.logger.debug(f"Event listener thread: Ignoring event type {event_type}")
                    pass

        except docker.errors.APIError as e:
            # Handle API errors specifically (e.g., connection lost during stream)
            self.logger.error(
                f"Event listener thread: Docker APIError: {e}. Listener stopping."
            )
            # Consider resetting docker_client to None here to force reconnect attempt
            self.docker_client = None
        except docker.errors.DockerException as e:
            # Catch other docker exceptions
            self.logger.error(
                f"Event listener thread: DockerException: {e}. Listener stopping."
            )
            self.docker_client = None
        except Exception as e:
            # Catch any other unexpected errors in the thread
            self.logger.exception(
                f"Event listener thread: Unexpected error: {e}. Listener stopping."
            )
        finally:
            # This block ensures the log message is printed even if events() returns (e.g., daemon stopped)
            self.logger.info("Event listener thread finished.")

    async def watch_events(self) -> None:
        """
        Watch Docker events non-blockingly using a separate thread.
        Includes reconnection logic for the listener thread.
        """
        self.logger.debug(
            "Docker source event watcher task started (using thread executor)."
        )

        while True:  # Keep trying to run the listener thread
            if not await self._reconnect_docker_client():
                self.logger.info(
                    "Event watcher task: Failed to connect to Docker. Retrying in 10 seconds..."
                )
                await asyncio.sleep(10)
                continue  # Go back to start of while loop to try reconnecting

            loop = asyncio.get_running_loop()
            listener_future = None
            try:
                # Run the blocking listener in a thread pool executor
                # self._blocking_event_listener requires the loop argument now
                listener_future = loop.run_in_executor(
                    None, self._blocking_event_listener, loop
                )
                await listener_future  # Wait for the listener thread to complete (which it shouldn't unless error/daemon stop)

                # If we get here, the listener thread exited. Log and prepare to restart.
                self.logger.warning(
                    "Event listener thread exited. Will attempt restart after delay."
                )
                # The thread itself should have logged the reason for exit.
                # Ensure docker_client is reset if the thread failed due to Docker issues.
                if self.docker_client is not None:
                    try:
                        # Quick check if connection is still valid
                        self.docker_client.ping()
                    except docker.errors.DockerException:
                        self.logger.info(
                            "Docker connection seems lost, resetting client."
                        )
                        self.docker_client = None

            except concurrent.futures.CancelledError:
                self.logger.info("Event watcher task cancelled.")
                # If the task was cancelled, cancel the executor future too
                if listener_future and not listener_future.done():
                    listener_future.cancel()
                break  # Exit the loop if the watcher task is cancelled
            except Exception as e:
                # Catch errors related to starting or managing the executor task
                self.logger.exception(
                    f"Error running or awaiting event listener thread: {e}"
                )
                # Consider if docker_client needs reset here too
                self.docker_client = None

            # Wait before restarting the listener attempt
            self.logger.info(
                "Waiting 10 seconds before attempting to restart listener thread..."
            )
            await asyncio.sleep(10)

    def _endpoints_from_container(self, container: Container) -> List[Endpoint]:
        """
        Generate endpoints from a single container's labels.

        Args:
            container: Docker container

        Returns:
            List[Endpoint]: List of endpoints
        """
        endpoints = []

        # Get container details
        container_id = container.id
        container_name = container.name
        container_labels = container.labels

        # Find all DNS hostnames defined in labels
        hostnames = self._get_hostnames_from_labels(container_labels)

        for hostname in hostnames:
            # Get DNS configuration from labels
            record_type = self._get_label_value(container_labels, hostname, "type", "A")
            ttl_str = self._get_label_value(container_labels, hostname, "ttl", None)
            proxied_str = self._get_label_value(
                container_labels, hostname, "proxied", "false"
            )
            target = self._get_label_value(container_labels, hostname, "target", None)
            network_name = self._get_label_value(
                container_labels, hostname, "network", None
            )  # Get network name from label

            # Convert TTL to integer
            record_ttl = int(ttl_str) if ttl_str and ttl_str.isdigit() else None

            # Convert proxied to boolean
            proxied = proxied_str.lower() == "true"

            # Get targets
            targets = []
            if target:
                # If a specific target is provided, use it directly
                targets = [target]
            elif record_type in ["A", "AAAA"]:
                # For A/AAAA records, find container IP on the specified or default network
                container_ip = self._get_container_ip(
                    container, network_name
                )  # Pass network_name
                if container_ip:
                    # Check if IP matches record type (IPv4 for A, IPv6 for AAAA)
                    ip_obj = ipaddress.ip_address(container_ip)
                    if record_type == "A" and isinstance(ip_obj, ipaddress.IPv4Address):
                        targets = [container_ip]
                    elif record_type == "AAAA" and isinstance(
                        ip_obj, ipaddress.IPv6Address
                    ):
                        targets = [container_ip]
                    else:
                        self.logger.warning(
                            f"IP address {container_ip} type mismatch for record type {record_type} on container {container_name}. Skipping."
                        )

            elif record_type == "CNAME":
                # For CNAME records, use container name as target if not specified
                # Note: Using container name might not be resolvable outside the Docker host's context.
                # Consider requiring an explicit target for CNAME or using a service discovery mechanism.
                targets = [
                    f"{container_name}"
                ]  # Default CNAME target to container name

            # Create endpoint if targets were determined
            if targets:
                endpoint = Endpoint(
                    dnsname=hostname,
                    targets=targets,
                    record_type=record_type,
                    record_ttl=record_ttl,
                    proxied=proxied,
                    container_id=container_id,  # Pass container ID
                    container_name=container_name,  # Pass container name for reference/logging
                )
                endpoints.append(endpoint)
                self.logger.debug(f"Created endpoint: {endpoint}")
            else:
                # Log why no endpoint was created (e.g., no suitable IP found)
                self.logger.warning(
                    f"No suitable target found for hostname {hostname} (Type: {record_type}, Network: {network_name or 'default'}) in container {container_name} ({container_id[:12]})"
                )

        return endpoints

    def _get_hostnames_from_labels(self, labels: Dict[str, str]) -> Set[str]:
        """
        Get all hostnames defined in container labels using the configured prefix.
        Handles both single 'hostname' label and multiple 'hostname.alias' labels.

        Args:
            labels: Container labels dictionary

        Returns:
            Set[str]: A set of unique hostnames found in labels.
        """
        hostnames = set()
        # Example: sherpa.dns/hostname=app.example.com
        hostname_label = f"{self.label_prefix}/hostname"
        if hostname_label in labels:
            # Support comma-separated hostnames in the main label
            names = [
                name.strip()
                for name in labels[hostname_label].split(",")
                if name.strip()
            ]
            hostnames.update(names)

        # Example: sherpa.dns/hostname.web=web.example.com, sherpa.dns/hostname.api=api.example.com
        hostname_prefix = f"{self.label_prefix}/hostname."
        for label, value in labels.items():
            if label.startswith(hostname_prefix):
                # The part after prefix is the alias, the value is the hostname
                # Support comma-separated hostnames in alias labels too
                names = [name.strip() for name in value.split(",") if name.strip()]
                hostnames.update(names)

        if not hostnames:
            self.logger.debug(
                "No hostnames found in labels using prefix %s", self.label_prefix
            )

        return hostnames

    def _get_label_value(
        self,
        labels: Dict[str, str],
        hostname: str,
        key: str,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get a label value for a specific hostname and key, supporting aliases.
        Looks for:
        1. sherpa.dns/hostname.<alias>.<key> (if hostname corresponds to an alias)
        2. sherpa.dns/<key>.<hostname> (hostname-specific key) - DEPRECATED STYLE? Should standardize.
        3. sherpa.dns/<key> (generic key)

        Args:
            labels: Container labels
            hostname: Hostname (which might be a value from hostname.alias label)
            key: Label key (e.g., 'ttl', 'type')
            default: Default value

        Returns:
            Optional[str]: Label value or default.
        """

        # Find if the hostname was defined via an alias label (e.g., sherpa.dns/hostname.web=...)
        alias_key = None
        hostname_alias_prefix = f"{self.label_prefix}/hostname."
        for label, value in labels.items():
            if label.startswith(hostname_alias_prefix):
                # Check if the current hostname is among the values of this alias label
                defined_hostnames = {
                    name.strip() for name in value.split(",") if name.strip()
                }
                if hostname in defined_hostnames:
                    alias_key = label[
                        len(hostname_alias_prefix) :
                    ]  # Extract the alias (e.g., 'web')
                    break  # Found the alias that defines this hostname

        # 1. Check for alias-specific key (e.g., sherpa.dns/ttl.web=60) - Preferred for aliased hostnames
        if alias_key:
            alias_specific_key = f"{self.label_prefix}/{key}.{alias_key}"
            if alias_specific_key in labels:
                return labels[alias_specific_key]

        # 2. Check for hostname-specific key (e.g., sherpa.dns/ttl.app.example.com=60) - Less common/maybe deprecated?
        # This style might conflict if hostname contains '.' - might need adjustment
        # hostname_specific_key = f"{self.label_prefix}/{key}.{hostname}"
        # if hostname_specific_key in labels:
        #     return labels[hostname_specific_key]

        # 3. Check for generic key (e.g., sherpa.dns/ttl=300) - Fallback for all hostnames on the container
        generic_key = f"{self.label_prefix}/{key}"
        if generic_key in labels:
            return labels[generic_key]

        return default

    def _get_container_ip(
        self, container: Container, network_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Get the IP address of a container, optionally specifying a network.
        Prefers IPv4 if available on the specified network.

        Args:
            container: Docker container object.
            network_name: Optional name of the Docker network.

        Returns:
            Optional[str]: IP address (string) or None if not found/error.
        """
        try:
            # Reload container attributes to get fresh network settings
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})

            if not networks:
                self.logger.warning(
                    f"No network settings found for container {container.name}"
                )
                return None

            target_network = None
            if network_name:
                if network_name in networks:
                    target_network = networks[network_name]
                else:
                    self.logger.warning(
                        f"Network '{network_name}' not found for container {container.name}. Available: {list(networks.keys())}"
                    )
                    return None
            elif len(networks) == 1:
                # If only one network, use it
                target_network = list(networks.values())[0]
            else:
                # If multiple networks and none specified, try common defaults or just pick one?
                # Trying 'bridge' or the first one alphabetically might be heuristics.
                # For now, let's prioritize bridge, then pick the first if no specific requested.
                if "bridge" in networks:
                    target_network = networks["bridge"]
                    self.logger.debug(
                        f"Multiple networks found for {container.name}, using default 'bridge'. Specify label '{self.label_prefix}/network' if needed."
                    )
                else:
                    first_network_name = sorted(networks.keys())[0]
                    target_network = networks[first_network_name]
                    self.logger.debug(
                        f"Multiple networks found for {container.name}, using first network '{first_network_name}'. Specify label '{self.label_prefix}/network' if needed."
                    )

            if target_network:
                ip_address = target_network.get("IPAddress")
                if ip_address and self._is_valid_ip(
                    ip_address
                ):  # Ensure it's a valid, non-empty IP
                    return ip_address
                else:
                    # Check for IPv6 if IPv4 is missing/invalid
                    ip_address_v6 = target_network.get("GlobalIPv6Address")
                    if ip_address_v6 and self._is_valid_ip(ip_address_v6):
                        return ip_address_v6
                    else:
                        self.logger.warning(
                            f"No valid IP address found for container {container.name} on network {network_name or 'selected network'}. Network details: {target_network}"
                        )

        except docker.errors.NotFound:
            self.logger.error(
                f"Container {container.name} not found during IP address retrieval."
            )
        except Exception as e:
            self.logger.exception(
                f"Error getting IP address for container {container.name}: {e}"
            )

        return None

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """Check if the string is a valid non-empty IP address."""
        if not ip:  # Check for empty string
            return False
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    @staticmethod
    def _matches_filter(labels: Dict[str, str], label_filter: str) -> bool:
        """
        Check if container labels match the filter expression.
        Filter format: "key=value" or "key".

        Args:
            labels: Container labels
            label_filter: Filter expression

        Returns:
            bool: True if labels match the filter, False otherwise
        """
        if "=" in label_filter:
            key, value = label_filter.split("=", 1)
            return labels.get(key) == value
        else:
            # Check for key existence
            return label_filter in labels
