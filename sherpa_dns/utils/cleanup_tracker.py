"""
Cleanup tracker module for Sherpa-DNS.

This module is responsible for tracking DNS records that are pending deletion
and determining when they are eligible for deletion.
"""

import logging
import re
import time
from typing import Dict, List

# Note: No internal imports needed for this file's core logic
# from sherpa_dns.models.models import Endpoint # Removed as Endpoint is not used here


class CleanupTracker:
    """
    Tracks DNS records that are pending deletion and determines when they are eligible for deletion.
    """

    def __init__(self, delay: str = "15m"):
        """
        Initialize a CleanupTracker.

        Args:
            delay: Delay before records are eligible for deletion (e.g., 15m, 1h, 30s)
        """
        self.delay = self._parse_duration(delay)
        self.original_delay_str = delay  # Store original string for logging
        self.pending_deletions: Dict[str, float] = {}  # Map of record ID to timestamp
        self.logger = logging.getLogger("sherpa-dns.cleanup-tracker")
        self.logger.debug(
            f"Cleanup delay set to {self.delay} seconds ({self.original_delay_str})"
        )

    def mark_for_deletion(self, record_id: str) -> None:
        """
        Mark a record for deletion with the current timestamp.

        Args:
            record_id: Record ID to mark for deletion
        """
        if record_id not in self.pending_deletions:
            self.pending_deletions[record_id] = time.time()
            self.logger.info(
                f"Marked record {record_id} for deletion (eligible in {self.original_delay_str})"
            )
        else:
            self.logger.debug(f"Record {record_id} is already marked for deletion.")

    def unmark_for_deletion(self, record_id: str) -> None:
        """
        Remove deletion mark if record is active again.

        Args:
            record_id: Record ID to unmark for deletion
        """
        if record_id in self.pending_deletions:
            del self.pending_deletions[record_id]
            self.logger.info(f"Unmarked record {record_id} for deletion")

    def get_eligible_for_deletion(self) -> List[str]:
        """
        Get records that have been pending deletion for longer than the delay.

        Returns:
            List[str]: List of record IDs eligible for deletion
        """
        eligible = []
        now = time.time()

        for record_id, timestamp in list(self.pending_deletions.items()):
            elapsed = now - timestamp
            if elapsed >= self.delay:
                self.logger.debug(
                    f"Record {record_id} eligible for deletion (elapsed: {elapsed:.2f}s >= delay: {self.delay}s)"
                )
                eligible.append(record_id)
                del self.pending_deletions[record_id]
                self.logger.info(f"Record {record_id} is eligible for deletion")
            else:
                self.logger.debug(
                    f"Record {record_id} still pending deletion (elapsed: {elapsed:.2f}s < delay: {self.delay}s)"
                )

        return eligible

    def get_pending_status(self) -> Dict[str, float]:
        """Returns a dictionary mapping pending record IDs to remaining seconds.
        Remaining time is positive if deletion is pending, negative if overdue (shouldn't happen often).
        """
        status = {}
        now = time.time()
        for record_id, timestamp in self.pending_deletions.items():
            time_until_eligible = (timestamp + self.delay) - now
            status[record_id] = time_until_eligible
        return status

    def _parse_duration(self, duration_str: str) -> int:
        """
        Parse a duration string like '15m' into seconds.

        Args:
            duration_str: Duration string

        Returns:
            int: Duration in seconds
        """
        if not duration_str:
            return 15 * 60  # Default to 15 minutes

        # Pattern for duration string (e.g., 15m, 1h, 30s)
        pattern = r"^(\d+)([smhd])$"
        match = re.match(pattern, duration_str)

        if not match:
            return 15 * 60  # Default to 15 minutes

        value, unit = match.groups()
        value = int(value)

        # Convert to seconds
        if unit == "s":
            return value
        elif unit == "m":
            return value * 60
        elif unit == "h":
            return value * 60 * 60
        elif unit == "d":
            return value * 60 * 60 * 24

        return 15 * 60  # Default to 15 minutes
