"""
Cloudflare provider module for Sherpa-DNS.

This module is responsible for interfacing with the Cloudflare API to manage DNS records.
"""

import logging
import re
from typing import Dict, List, Optional

import cloudflare

from sherpa_dns.models.models import Changes, Endpoint


class CloudflareProvider:
    """
    Provider that interfaces with the Cloudflare API.
    """

    def __init__(
        self,
        api_token: str,
        domain_filter: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        proxied_by_default: bool = False,
        dry_run: bool = False,
    ):
        """
        Initialize a CloudflareProvider.

        Args:
            api_token: Cloudflare API token
            domain_filter: List of domains to include
            exclude_domains: List of domains to exclude
            proxied_by_default: Whether to proxy records by default
            dry_run: Whether to run in dry-run mode
        """
        self.api_token = api_token
        self.domain_filter = domain_filter or []
        self.exclude_domains = exclude_domains or []
        self.proxied_by_default = proxied_by_default
        self.dry_run = dry_run
        self.logger = logging.getLogger("sherpa-dns.provider.cloudflare")

        # Initialize Cloudflare client - use lowercase class name and api_token argument
        self.cf = cloudflare.Cloudflare(api_token=api_token)

        # Cache for zone IDs
        self.zone_id_cache: Dict[str, str] = {}

    async def zones(self) -> List[Dict[str, str]]:
        """
        Returns a list of managed zones that match the domain filter.

        Returns:
            List[Dict[str, str]]: List of zones
        """
        self.logger.debug("Attempting to fetch zones from Cloudflare API...")
        try:
            # Get all zones using list method and direct keyword arguments
            zones_iterator = self.cf.zones.list(per_page=100)
            zones = list(zones_iterator)

            self.logger.debug(f"Received {len(zones)} raw zones from Cloudflare API.")
            if not zones:
                self.logger.warning("Cloudflare API returned an empty list of zones.")
            else:
                # Log the names of received zones using attribute access
                zone_names = [getattr(zone, "name", "N/A") for zone in zones]
                self.logger.debug(f"Raw zone names received: {zone_names}")

            # Filter zones
            filtered_zones = []
            self.logger.debug(
                f"Filtering zones based on domain_filter: {self.domain_filter} and exclude_domains: {self.exclude_domains}"
            )
            for zone in zones:
                # Use attribute access
                zone_name = getattr(zone, "name", None)
                zone_id = getattr(zone, "id", None)
                if not zone_name or not zone_id:
                    self.logger.warning(
                        f"Skipping zone object due to missing name or id: {zone}"
                    )
                    continue

                self.logger.debug(
                    f"Processing zone: Name='{zone_name}', ID='{zone_id}'"
                )

                # Check if zone should be excluded
                if self._matches_domain_filter(zone_name, self.exclude_domains):
                    self.logger.debug(
                        f"Zone '{zone_name}' is in exclude_domains, skipping."
                    )
                    continue

                # Check if zone is in include filter (if filter is defined)
                if self.domain_filter and not self._matches_domain_filter(
                    zone_name, self.domain_filter
                ):
                    self.logger.debug(
                        f"Zone '{zone_name}' is not in domain_filter, skipping."
                    )
                    continue

                self.logger.debug(
                    f"Zone '{zone_name}' passed filters. Adding to managed zones."
                )
                # Store as dict for consistency with downstream usage (might need refactor later)
                filtered_zones.append({"id": zone_id, "name": zone_name})

                # Cache zone ID
                self.zone_id_cache[zone_name] = zone_id

            self.logger.debug(
                f"Finished filtering. Found {len(filtered_zones)} managed zones."
            )
            return filtered_zones
        # Use cloudflare.APIError for specific API errors
        except cloudflare.APIError as e:
            error_code = getattr(e, "code", "N/A")
            error_message = getattr(e, "message", str(e))
            self.logger.error(
                f"Cloudflare API Error fetching zones: {e} (Code: {error_code}, Message: {error_message})"
            )
            return []
        # Catch other potential Cloudflare errors
        except cloudflare.CloudflareError as e:
            self.logger.error(f"General Cloudflare Error fetching zones: {e}")
            return []
        except Exception as e:
            self.logger.exception(
                f"An unexpected error occurred while fetching zones: {e}"
            )
            return []

    async def records(self) -> List[Endpoint]:
        """
        Returns a list of all DNS records in managed zones.

        Returns:
            List[Endpoint]: List of endpoints
        """
        endpoints = []

        # Get managed zones
        zones = await self.zones()

        for zone in zones:
            # These come from the dict created in zones() method
            zone_id = zone["id"]
            zone_name = zone["name"]

            try:
                # Get all DNS records for the zone using client.dns.records
                dns_records_iterator = self.cf.dns.records.list(
                    zone_id=zone_id, per_page=100
                )
                dns_records = list(dns_records_iterator)

                for record in dns_records:
                    # Use attribute access for record object
                    record_type = getattr(record, "type", None)
                    record_name = getattr(record, "name", None)
                    record_content = getattr(record, "content", None)
                    record_ttl = getattr(
                        record, "ttl", None
                    )  # Default handled by Endpoint
                    record_proxied = getattr(
                        record, "proxied", False
                    )  # Default handled by Endpoint

                    if not all([record_type, record_name, record_content]):
                        self.logger.warning(
                            f"Skipping record object due to missing type, name, or content: {record}"
                        )
                        continue

                    # Skip TXT records (they are managed by the registry)
                    if record_type == "TXT":
                        continue

                    # Create endpoint
                    endpoint = Endpoint(
                        dnsname=record_name,
                        targets=[record_content],  # Assuming single content for non-TXT
                        record_type=record_type,
                        record_ttl=record_ttl,
                        proxied=record_proxied,
                    )
                    endpoints.append(endpoint)
            # Use cloudflare.APIError for specific API errors
            except cloudflare.APIError as e:
                error_code = getattr(e, "code", "N/A")
                error_message = getattr(e, "message", str(e))
                self.logger.error(
                    f"Cloudflare API Error fetching records for zone {zone_name}: {e} (Code: {error_code}, Message: {error_message})"
                )
            # Catch other potential Cloudflare errors
            except cloudflare.CloudflareError as e:
                self.logger.error(
                    f"General Cloudflare Error fetching records for zone {zone_name}: {e}"
                )
            except Exception as e:
                self.logger.exception(
                    f"An unexpected error occurred while fetching records for zone {zone_name}: {e}"
                )

        return endpoints

    async def apply_changes(self, changes: Changes) -> None:
        """
        Applies the specified changes to DNS records.

        Args:
            changes: Changes to apply
        """
        if self.dry_run:
            self.logger.info("Dry run mode, not applying changes")
            return

        # Create new records
        for endpoint in changes.create:
            await self._create_record(endpoint)

        # Update existing records
        for i in range(len(changes.update_old)):
            old_endpoint = changes.update_old[i]
            new_endpoint = changes.update_new[i]
            await self._update_record(old_endpoint, new_endpoint)

        # Delete records
        for endpoint in changes.delete:
            await self._delete_record(endpoint)

    async def _create_record(self, endpoint: Endpoint) -> None:
        """
        Creates a new DNS record.

        Args:
            endpoint: Endpoint to create
        """
        # Get zone ID for the endpoint
        zone_id = await self._get_zone_id_for_endpoint(endpoint)
        if not zone_id:
            self.logger.error(f"Could not find zone ID for endpoint {endpoint.dnsname}")
            return

        # Create record
        try:
            for target in endpoint.targets:
                # Prepare record data according to v4 schema
                # Revert TTL logic: Use endpoint TTL if provided, otherwise use 1 (Auto)
                record_ttl = (
                    endpoint.record_ttl if endpoint.record_ttl is not None else 1
                )

                record_data = {
                    "name": endpoint.dnsname,
                    "type": endpoint.record_type,
                    "content": target,
                    "proxied": endpoint.proxied,
                    "ttl": record_ttl,  # Use original TTL logic (1=Auto)
                }

                self.logger.info(
                    f"Creating DNS record: {endpoint.record_type} {record_data['name']} -> {record_data['content']} (TTL: {record_data.get('ttl', 'Auto')}, Proxied: {record_data['proxied']})"
                )
                # Use create method from client.dns.records with direct keyword arguments
                self.cf.dns.records.create(
                    zone_id=zone_id,
                    name=record_data["name"],
                    type=record_data["type"],
                    content=record_data["content"],
                    ttl=record_data["ttl"],
                    proxied=record_data["proxied"],
                )
        # Use cloudflare.APIError for specific API errors
        except cloudflare.APIError as e:
            error_code = getattr(e, "code", "N/A")
            error_message = getattr(e, "message", str(e))
            self.logger.error(
                f"Cloudflare API Error creating DNS record for {endpoint.dnsname}: {e} (Code: {error_code}, Message: {error_message})"
            )
        except cloudflare.CloudflareError as e:
            self.logger.error(
                f"General Cloudflare Error creating DNS record for {endpoint.dnsname}: {e}"
            )
        except Exception as e:
            self.logger.exception(
                f"An unexpected error occurred while creating DNS record for {endpoint.dnsname}: {e}"
            )

    async def _update_record(
        self, old_endpoint: Endpoint, new_endpoint: Endpoint
    ) -> None:
        """
        Updates an existing DNS record.

        Args:
            old_endpoint: Old endpoint
            new_endpoint: New endpoint
        """
        # Get zone ID for the endpoint
        zone_id = await self._get_zone_id_for_endpoint(new_endpoint)
        if not zone_id:
            self.logger.error(
                f"Could not find zone ID for endpoint {new_endpoint.dnsname}"
            )
            return

        # Get record ID
        # Use old_endpoint to find the record to update
        record_id = await self._get_record_id(zone_id, old_endpoint)
        if not record_id:
            # If old record not found, try creating the new one instead of failing
            self.logger.warning(
                f"Record ID not found for updating {old_endpoint.dnsname} ({old_endpoint.record_type}). Attempting to create instead."
            )
            await self._create_record(new_endpoint)
            return

        # Update record
        try:
            # Ensure targets list is not empty for new_endpoint
            if not new_endpoint.targets:
                self.logger.error(
                    f"Cannot update record {new_endpoint.dnsname}: No targets specified."
                )
                return

            # Prepare record data according to v4 schema
            record_ttl = (
                new_endpoint.record_ttl if new_endpoint.record_ttl is not None else 1
            )  # Revert TTL logic (1=Auto)
            record_data = {
                "name": new_endpoint.dnsname,
                "type": new_endpoint.record_type,
                "content": new_endpoint.targets[0],  # Use first target for update
                "proxied": new_endpoint.proxied,
                "ttl": record_ttl,  # Use original TTL logic (1=Auto)
            }

            self.logger.info(
                f"Updating DNS record: {record_id} ({old_endpoint.dnsname} -> {new_endpoint.dnsname}) Type: {new_endpoint.record_type}, Content: {record_data['content']}, TTL: {record_data.get('ttl', 'Auto')}, Proxied: {record_data['proxied']})"
            )
            # Use update method from client.dns.records with direct keyword arguments
            self.cf.dns.records.update(
                dns_record_id=record_id,
                zone_id=zone_id,
                name=record_data["name"],
                type=record_data["type"],
                content=record_data["content"],
                ttl=record_data["ttl"],
                proxied=record_data["proxied"],
            )
        # Use cloudflare.APIError for specific API errors
        except cloudflare.APIError as e:
            error_code = getattr(e, "code", "N/A")
            self.logger.error(
                f"Cloudflare API Error updating DNS record {record_id} for {new_endpoint.dnsname}: {e} (Code: {error_code})"
            )
        except cloudflare.CloudflareError as e:
            self.logger.error(
                f"General Cloudflare Error updating DNS record {record_id} for {new_endpoint.dnsname}: {e}"
            )
        except Exception as e:
            self.logger.exception(
                f"An unexpected error occurred while updating DNS record for {new_endpoint.dnsname}: {e}"
            )

    async def _delete_record(self, endpoint: Endpoint) -> None:
        """
        Deletes a DNS record.

        Args:
            endpoint: Endpoint to delete
        """
        # Get zone ID for the endpoint
        zone_id = await self._get_zone_id_for_endpoint(endpoint)
        if not zone_id:
            self.logger.error(
                f"Could not find zone ID for endpoint {endpoint.dnsname} during deletion."
            )
            return

        # Get record ID
        record_id = await self._get_record_id(zone_id, endpoint)
        if not record_id:
            self.logger.warning(
                f"Could not find record ID for deleting endpoint {endpoint.dnsname} ({endpoint.record_type}). Skipping deletion."
            )
            return

        # Delete record
        try:
            # Include record type in the log message
            self.logger.info(
                f"Deleting DNS record: {endpoint.record_type} {endpoint.dnsname} (ID: {record_id})"
            )
            # Use delete method from client.dns.records with zone_id and record_id kwargs
            self.cf.dns.records.delete(dns_record_id=record_id, zone_id=zone_id)
        # Use cloudflare.APIError for specific API errors
        except cloudflare.APIError as e:
            error_code = getattr(e, "code", "N/A")
            error_message = getattr(e, "message", str(e))
            self.logger.error(
                f"Cloudflare API Error deleting DNS record {record_id} for {endpoint.dnsname}: {e} (Code: {error_code}, Message: {error_message})"
            )
        except cloudflare.CloudflareError as e:
            self.logger.error(
                f"General Cloudflare Error deleting DNS record {record_id} for {endpoint.dnsname}: {e}"
            )
        except Exception as e:
            self.logger.exception(
                f"An unexpected error occurred while deleting DNS record for {endpoint.dnsname}: {e}"
            )

    async def _get_zone_id_for_endpoint(self, endpoint: Endpoint) -> Optional[str]:
        """
        Gets the zone ID for an endpoint.

        Args:
            endpoint: Endpoint

        Returns:
            Optional[str]: Zone ID
        """
        # Extract domain from endpoint
        domain = self._extract_domain_from_hostname(endpoint.dnsname)
        self.logger.debug(f"Extracted domain: {domain}")
        if not domain:
            return None

        # Check cache
        if domain in self.zone_id_cache:
            return self.zone_id_cache[domain]

        # Get zones (returns list of dicts now, as processed in zones() method)
        zones = await self.zones()
        self.logger.debug(f"Checking against managed zones: {zones}")
        # Find matching zone (comparing domain against dict 'name' key)
        for zone in zones:
            zone_name = zone.get("name")
            zone_id = zone.get("id")
            if not zone_name or not zone_id:
                continue  # Should not happen if zones() filters correctly

            self.logger.debug(f"Checking zone: {zone_name}")
            if zone_name == domain:
                # Zone ID is already cached by zones() call, but return it directly
                self.logger.debug(
                    f"Found matching zone ID: {zone_id} for domain {domain}"
                )
                # Ensure cache consistency (though zones() should handle this)
                self.zone_id_cache[domain] = zone_id
                return zone_id

        self.logger.warning(
            f"No matching zone found for domain: {domain} among managed zones."
        )
        return None

    async def _get_record_id(self, zone_id: str, endpoint: Endpoint) -> Optional[str]:
        """
        Gets the record ID for an endpoint.

        Args:
            zone_id: Zone ID
            endpoint: Endpoint

        Returns:
            Optional[str]: Record ID
        """
        try:
            # Get all DNS records for the zone using client.dns.records and zone_id kwarg
            dns_records_iterator = self.cf.dns.records.list(
                zone_id=zone_id,
                name=endpoint.dnsname,
                type=endpoint.record_type,
                per_page=5,  # Usually only expect 1, but check a few
            )
            dns_records = list(dns_records_iterator)

            # Find matching record (v4 returns objects with attributes)
            for record in dns_records:
                # Use attribute access with getattr for safety
                record_name = getattr(record, "name", None)
                record_type = getattr(record, "type", None)
                record_id = getattr(record, "id", None)

                if (
                    record_name == endpoint.dnsname
                    and record_type == endpoint.record_type
                    and record_id
                ):
                    # Found the specific record
                    return record_id

            self.logger.debug(
                f"Did not find existing record ID for {endpoint.dnsname} ({endpoint.record_type}) in zone {zone_id}"
            )
            return None
        # Use cloudflare.APIError for specific API errors
        except cloudflare.APIError as e:
            error_code = getattr(e, "code", "N/A")
            error_message = getattr(e, "message", str(e))
            self.logger.error(
                f"Cloudflare API Error getting record ID for {endpoint.dnsname}: {e} (Code: {error_code}, Message: {error_message})"
            )
            return None
        except cloudflare.CloudflareError as e:
            self.logger.error(
                f"General Cloudflare Error getting record ID for {endpoint.dnsname}: {e}"
            )
            return None
        except Exception as e:
            self.logger.exception(
                f"An unexpected error occurred while getting record ID for {endpoint.dnsname}: {e}"
            )
            return None

    @staticmethod
    def _extract_domain_from_hostname(hostname: str) -> Optional[str]:
        """
        Extracts the domain from a hostname.

        Args:
            hostname: Hostname

        Returns:
            Optional[str]: Domain
        """
        # Split hostname into parts
        parts = hostname.split(".")

        # Handle special cases
        if len(parts) <= 1:
            return None

        # For hostnames with more than 2 parts, try to find the domain
        if len(parts) > 2:
            # Check for common TLDs
            if parts[-2] + "." + parts[-1] in [
                "com.au",
                "co.uk",
                "co.nz",
                "co.za",
                "com.br",
                "com.mx",
            ]:
                return ".".join(parts[-3:])

            # Default to last 2 parts
            return ".".join(parts[-2:])

        # For hostnames with exactly 2 parts, use the whole hostname
        return hostname

    @staticmethod
    def _matches_domain_filter(domain: str, domain_filter: List[str]) -> bool:
        """
        Check if a domain matches the domain filter.

        Args:
            domain: Domain
            domain_filter: Domain filter list

        Returns:
            bool: True if the domain matches any entry in the filter, False otherwise
        """
        if not domain_filter:
            # If the filter list is empty, no match is possible.
            return False

        for filter_domain in domain_filter:
            # Check for wildcard
            if filter_domain.startswith("*."):
                # Convert wildcard to regex
                pattern = "^.*\\." + re.escape(filter_domain[2:]) + "$"
                if re.match(pattern, domain):
                    # Found a wildcard match
                    return True
            elif filter_domain == domain:
                # Found an exact match
                return True

        # If the loop completes without finding any match in the list
        return False
