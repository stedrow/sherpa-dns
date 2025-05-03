"""
TXT registry module for Sherpa-DNS.

This module is responsible for tracking which DNS records are managed by Sherpa-DNS
using TXT records.
"""

import base64
import logging
from typing import Dict, List, Optional

import cloudflare
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from sherpa_dns.models.models import Changes, Endpoint


class TXTRegistry:
    """
    Registry that tracks DNS records using TXT records.
    """

    def __init__(
        self,
        provider,
        txt_prefix: str = "sherpa-dns-",
        txt_owner_id: str = "default",
        txt_wildcard_replacement: str = "star",
        encrypt_txt: bool = False,
        encryption_key: Optional[str] = None,
    ):
        """
        Initialize a TXTRegistry.

        Args:
            provider: DNS provider
            txt_prefix: Prefix for TXT records
            txt_owner_id: Owner ID for TXT records
            txt_wildcard_replacement: Replacement for wildcards in TXT records
            encrypt_txt: Whether to encrypt TXT records
            encryption_key: Encryption key for TXT records
        """
        self.provider = provider
        self.txt_prefix = txt_prefix
        self.txt_owner_id = txt_owner_id
        self.txt_wildcard_replacement = txt_wildcard_replacement
        self.encrypt_txt = encrypt_txt
        self.encryption_key = encryption_key
        self.logger = logging.getLogger("sherpa-dns.registry.txt")

        # Initialize encryption if enabled
        self.fernet = None
        if self.encrypt_txt and self.encryption_key:
            self.fernet = self._create_fernet(self.encryption_key)

    async def records(self) -> List[Endpoint]:
        """
        Returns a list of all DNS records managed by this Sherpa-DNS instance.

        Returns:
            List[Endpoint]: List of endpoints
        """
        # Get all records from provider
        all_records = await self.provider.records()

        # Get all TXT records
        txt_records = await self._get_txt_records()

        # Filter records based on TXT records
        managed_records = []
        for record in all_records:
            # Get TXT record name for this record
            txt_record_name = self._get_txt_record_name(record)

            # Check if TXT record exists
            if txt_record_name in txt_records:
                # Check if TXT record is owned by this instance
                txt_content = txt_records[txt_record_name]
                if self._is_owned_by_this_instance(txt_content):
                    # Parse TXT record content
                    parsed_content = self._parse_txt_content(txt_content)

                    # Update record with parsed content, specifically handling TTL='auto'
                    if "ttl" in parsed_content:
                        ttl_value = parsed_content["ttl"]
                        if ttl_value == "auto":
                            record.record_ttl = 1
                        else:
                            try:
                                record.record_ttl = int(ttl_value)
                            except ValueError:
                                self.logger.warning(
                                    f"Could not parse TTL value '{ttl_value}' from TXT record for {record.dnsname}. Skipping TTL update."
                                )

                    managed_records.append(record)

        return managed_records

    async def sync(self, changes: Changes) -> None:
        """
        Synchronizes the desired state with the current state.

        Args:
            changes: Changes to apply
        """
        # Apply changes to DNS records
        await self.provider.apply_changes(changes)

        # Create TXT records for new endpoints
        for endpoint in changes.create:
            await self._create_txt_record(endpoint)

        # Update TXT records for updated endpoints
        for i in range(len(changes.update_old)):
            old_endpoint = changes.update_old[i]
            new_endpoint = changes.update_new[i]
            await self._update_txt_record(old_endpoint, new_endpoint)

        # Delete TXT records for deleted endpoints
        for endpoint in changes.delete:
            await self._delete_txt_record(endpoint)

    async def get_managed_endpoints(self) -> List[Endpoint]:
        """
        Returns a list of all endpoints managed by this Sherpa-DNS instance.

        Returns:
            List[Endpoint]: List of managed endpoints
        """
        return await self.records()

    def _get_txt_record_name(self, endpoint: Endpoint) -> str:
        """
        Gets the TXT record name based on the endpoint's DNS name,
        applying the configured prefix.

        Args:
            endpoint: Endpoint

        Returns:
            str: TXT record name
        """
        # Start with the prefixed name
        txt_name = f"{self.txt_prefix}{endpoint.dnsname}"

        # Replace wildcard character if present
        if "*" in txt_name:
            txt_name = txt_name.replace("*", self.txt_wildcard_replacement)
            self.logger.debug(
                f"Replaced wildcard in TXT name for {endpoint.dnsname}: {txt_name}"
            )

        return txt_name

    def _get_txt_record_content(self, endpoint: Endpoint) -> str:
        """
        Creates the content for a TXT record, optionally encrypting it.

        Args:
            endpoint: Endpoint

        Returns:
            str: TXT record content
        """
        content = {
            "heritage": "sherpa-dns",
            "owner": self.txt_owner_id,
            "resource": "docker",
        }

        if endpoint.targets:
            content["targets"] = ",".join(endpoint.targets)

        # Special handling for TTL in TXT record content
        if endpoint.record_ttl is not None:
            if endpoint.record_ttl == 1:
                content["ttl"] = "auto"  # Represent TTL 1 as 'auto'
            else:
                content["ttl"] = str(endpoint.record_ttl)

        # Convert to string
        content_str = ",".join([f"{k}={v}" for k, v in content.items()])

        if self.encrypt_txt and self.fernet:
            # Encrypt the content
            return self._encrypt_txt_content(content_str)

        return content_str

    def _encrypt_txt_content(self, content: str) -> str:
        """
        Encrypts the TXT record content using AES-256.

        Args:
            content: TXT record content

        Returns:
            str: Encrypted TXT record content
        """
        if not self.fernet:
            return content

        # Encrypt the content
        encrypted = self.fernet.encrypt(content.encode())

        # Return as base64-encoded string with version prefix
        return f"v1:AES256:{encrypted.decode()}"

    def _decrypt_txt_content(self, content: str) -> Optional[str]:
        """
        Decrypts the TXT record content.

        Args:
            content: Encrypted TXT record content

        Returns:
            Optional[str]: Decrypted TXT record content
        """
        if not self.fernet:
            return content

        # Check if content is encrypted
        if not content.startswith("v1:AES256:"):
            return content

        try:
            # Extract encrypted content
            encrypted = content[10:]

            # Decrypt the content
            decrypted = self.fernet.decrypt(encrypted.encode())

            return decrypted.decode()
        except Exception as e:
            self.logger.error(f"Error decrypting TXT record content: {e}")
            return None

    def _create_fernet(self, key: str) -> Fernet:
        """
        Creates a Fernet instance for encryption/decryption.

        Args:
            key: Encryption key

        Returns:
            Fernet: Fernet instance
        """
        # Use PBKDF2 to derive a key from the provided key
        salt = b"sherpa-dns"  # Fixed salt for deterministic key derivation
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000
        )
        key_bytes = kdf.derive(key.encode())

        # Encode key as URL-safe base64
        key_base64 = base64.urlsafe_b64encode(key_bytes)

        return Fernet(key_base64)

    async def _get_txt_records(self) -> Dict[str, str]:
        """
        Gets all TXT records from the provider.

        Returns:
            Dict[str, str]: Dictionary of TXT record name to content
        """
        txt_records = {}

        # Get managed zones
        zones = await self.provider.zones()

        for zone in zones:
            zone_id = zone["id"]
            zone_name = zone["name"]

            try:
                # Get all TXT records for the zone using client.dns.records.list
                dns_records_iterator = self.provider.cf.dns.records.list(
                    zone_id=zone_id, type="TXT", per_page=100
                )
                # Convert iterator to list
                dns_records = list(dns_records_iterator)

                for record in dns_records:
                    # Use attribute access now since v4 returns objects
                    record_type = getattr(record, "type", None)
                    record_name = getattr(record, "name", None)
                    raw_content = getattr(record, "content", None)

                    # Check if record is a TXT record and has necessary attributes
                    if (
                        record_type == "TXT"
                        and record_name is not None
                        and raw_content is not None
                    ):
                        # Strip quotes BEFORE processing (parsing or decryption)
                        content_to_process = raw_content
                        if raw_content.startswith('"') and raw_content.endswith('"'):
                            content_to_process = raw_content[1:-1]

                        processed_content = (
                            content_to_process  # Default to stripped content
                        )

                        # Decrypt content if encryption is enabled for the registry
                        if self.encrypt_txt:
                            # Pass the unquoted content to the decryption function
                            processed_content = self._decrypt_txt_content(
                                content_to_process
                            )

                        # Add to dictionary if content was successfully processed/decrypted
                        if processed_content:
                            txt_records[record_name] = processed_content
                        else:
                            # Log if decryption failed (decrypt returns None on error)
                            if self.encrypt_txt and content_to_process.startswith(
                                "v1:AES256:"
                            ):
                                self.logger.warning(
                                    f"Failed to decrypt TXT record content for {record_name}. Record might be ignored."
                                )
            # Catch Cloudflare specific API errors first
            except cloudflare.APIError as e:
                error_code = getattr(e, "code", "N/A")
                error_message = getattr(e, "message", str(e))
                self.logger.error(
                    f"Cloudflare API Error fetching TXT records for zone {zone_name}: {e} (Code: {error_code}, Message: {error_message})"
                )
            # Catch other Cloudflare errors
            except cloudflare.CloudflareError as e:
                self.logger.error(
                    f"General Cloudflare Error fetching TXT records for zone {zone_name}: {e}"
                )
            # Catch any other unexpected errors
            except Exception as e:
                # Log the full traceback for unexpected errors
                self.logger.exception(
                    f"An unexpected error occurred while fetching TXT records for zone {zone_name}: {e}"
                )

        return txt_records

    def _is_owned_by_this_instance(self, txt_content: str) -> bool:
        """
        Checks if a TXT record is owned by this Sherpa-DNS instance.

        Args:
            txt_content: TXT record content

        Returns:
            bool: True if the TXT record is owned by this instance, False otherwise
        """
        # Parse TXT record content
        parsed_content = self._parse_txt_content(txt_content)

        # Check if heritage is sherpa-dns
        if parsed_content.get("heritage") != "sherpa-dns":
            return False

        # Check if owner is this instance
        if parsed_content.get("owner") != self.txt_owner_id:
            return False

        return True

    def _parse_txt_content(self, txt_content: str) -> Dict[str, str]:
        """
        Parses TXT record content into a dictionary.
        Format: "heritage=sherpa-dns,owner=default,resource=docker,ttl=auto"

        Args:
            txt_content: TXT record content

        Returns:
            Dict[str, str]: Parsed TXT record content
        """
        # Strip leading/trailing quotes if present
        if txt_content.startswith('"') and txt_content.endswith('"'):
            txt_content = txt_content[1:-1]

        parsed_content = {}
        try:
            # Use dict comprehension for parsing
            parsed_content = {
                key.strip(): value.strip()
                for part in txt_content.split(",")
                if "=" in part  # Ensure there's a separator
                for key, value in [part.split("=", 1)]  # Split only once
            }
        except ValueError as e:
            # Log error if splitting fails unexpectedly
            self.logger.warning(
                f"Could not parse TXT content: '{txt_content}'. Error: {e}"
            )
            return {}  # Return empty dict on error

        return parsed_content

    async def _create_txt_record(self, endpoint: Endpoint) -> None:
        """
        Creates a TXT record for an endpoint.

        Args:
            endpoint: Endpoint
        """
        # Get TXT record name
        txt_record_name = self._get_txt_record_name(endpoint)

        # Get TXT record content
        txt_record_content = self._get_txt_record_content(endpoint)

        # Create TXT record
        txt_endpoint = Endpoint(
            dnsname=txt_record_name,
            targets=[f'"{txt_record_content}"'],
            record_type="TXT",
        )

        # Create TXT record
        await self.provider._create_record(txt_endpoint)

    async def _update_txt_record(
        self, old_endpoint: Endpoint, new_endpoint: Endpoint
    ) -> None:
        """
        Updates a TXT record for an endpoint.

        Args:
            old_endpoint: Old endpoint
            new_endpoint: New endpoint
        """
        # Get old TXT record name
        old_txt_record_name = self._get_txt_record_name(old_endpoint)

        # Get new TXT record name
        new_txt_record_name = self._get_txt_record_name(new_endpoint)

        # Get TXT record content
        txt_record_content = self._get_txt_record_content(new_endpoint)

        # Create new TXT endpoint
        new_txt_endpoint = Endpoint(
            dnsname=new_txt_record_name,
            targets=[f'"{txt_record_content}"'],
            record_type="TXT",
        )

        # If TXT record name has changed, delete old TXT record and create new one
        if old_txt_record_name != new_txt_record_name:
            # Create old TXT endpoint
            old_txt_endpoint = Endpoint(
                dnsname=old_txt_record_name, targets=[], record_type="TXT"
            )

            # Delete old TXT record
            await self.provider._delete_record(old_txt_endpoint)

            # Create new TXT record
            await self.provider._create_record(new_txt_endpoint)
        else:
            # Create old TXT endpoint
            old_txt_endpoint = Endpoint(
                dnsname=old_txt_record_name, targets=[], record_type="TXT"
            )

            # Update TXT record
            await self.provider._update_record(old_txt_endpoint, new_txt_endpoint)

    async def _delete_txt_record(self, endpoint: Endpoint) -> None:
        """
        Deletes a TXT record for an endpoint.

        Args:
            endpoint: Endpoint
        """
        # Get TXT record name
        txt_record_name = self._get_txt_record_name(endpoint)

        # Create TXT endpoint
        txt_endpoint = Endpoint(dnsname=txt_record_name, targets=[], record_type="TXT")

        # Delete TXT record
        await self.provider._delete_record(txt_endpoint)
