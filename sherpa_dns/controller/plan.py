"""
Plan module for Sherpa-DNS.

This module is responsible for calculating the changes needed to bring the current state
in line with the desired state.
"""

import logging
from typing import Dict, List

from sherpa_dns.models.models import Changes, Endpoint


class Plan:
    """
    Plan calculates the changes needed to bring the current state in line with the desired state.
    """

    def __init__(
        self, current: List[Endpoint], desired: List[Endpoint], policy: str = "sync"
    ):
        """
        Initialize a Plan.

        Args:
            current: Current endpoints
            desired: Desired endpoints
            policy: Synchronization policy (sync, upsert-only, create-only)
        """
        self.current = current
        self.desired = desired
        self.policy = policy
        self.logger = logging.getLogger("sherpa-dns.plan")

    def calculate_changes(self) -> Changes:
        """
        Calculate the changes needed to bring the current state in line with the desired state.

        Returns:
            Changes: Changes to be applied
        """
        changes = Changes()

        # Index current endpoints by ID for faster lookup
        current_by_id: Dict[str, Endpoint] = {
            endpoint.id: endpoint for endpoint in self.current
        }

        # Process desired endpoints
        for desired_endpoint in self.desired:
            current_endpoint = current_by_id.get(desired_endpoint.id)

            if current_endpoint:
                # Endpoint exists, check if it needs to be updated
                if self._needs_update(current_endpoint, desired_endpoint):
                    self.logger.info(f"Endpoint {desired_endpoint.id} needs update")
                    changes.update_old.append(current_endpoint)
                    changes.update_new.append(desired_endpoint)
                else:
                    self.logger.debug(f"Endpoint {desired_endpoint.id} is up-to-date")
            else:
                # Endpoint doesn't exist, create it
                self.logger.info(f"Endpoint {desired_endpoint.id} will be created")
                changes.create.append(desired_endpoint)

        # Process current endpoints that are not in desired endpoints
        if self.policy == "sync":
            desired_ids = {endpoint.id for endpoint in self.desired}
            for current_endpoint in self.current:
                if current_endpoint.id not in desired_ids:
                    self.logger.debug(
                        f"Endpoint {current_endpoint.id} ({current_endpoint.dnsname}) identified as no longer desired."
                    )
                    changes.delete.append(current_endpoint)

        return changes

    @staticmethod
    def _needs_update(current: Endpoint, desired: Endpoint) -> bool:
        """
        Check if an endpoint needs to be updated.

        Args:
            current: Current endpoint
            desired: Desired endpoint

        Returns:
            bool: True if the endpoint needs to be updated, False otherwise
        """
        # Check if targets are different
        if set(current.targets) != set(desired.targets):
            return True

        # Check if TTL is different
        if current.record_ttl != desired.record_ttl:
            return True

        # Check if proxied status is different
        if current.proxied != desired.proxied:
            return True

        return False

    @classmethod
    def deletion_only(cls, endpoints: List[Endpoint]) -> Changes:
        """
        Create a plan that only deletes the specified endpoints.

        Args:
            endpoints: Endpoints to delete

        Returns:
            Changes: Changes to be applied
        """
        changes = Changes()
        changes.delete = endpoints
        return changes
