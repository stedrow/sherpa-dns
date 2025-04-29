"""
Data models for Sherpa-DNS.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Endpoint:
    """
    Represents a DNS endpoint (record) to be managed by Sherpa-DNS.
    """

    dnsname: str
    targets: List[str]
    record_type: str
    record_ttl: Optional[int] = None
    proxied: bool = False
    container_id: Optional[str] = None
    container_name: Optional[str] = None

    @property
    def id(self) -> str:
        """
        Generate a unique identifier for this endpoint.

        Returns:
            str: Unique identifier
        """
        return f"{self.dnsname}:{self.record_type}"


@dataclass
class Changes:
    """
    Represents changes to be applied to DNS records.
    """

    create: List[Endpoint] = field(default_factory=list)
    update_old: List[Endpoint] = field(default_factory=list)
    update_new: List[Endpoint] = field(default_factory=list)
    delete: List[Endpoint] = field(default_factory=list)

    def has_changes(self) -> bool:
        """
        Check if there are any changes to be applied.

        Returns:
            bool: True if there are changes, False otherwise
        """
        return bool(self.create or self.update_old or self.delete)
