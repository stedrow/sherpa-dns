"""
Configuration module for Sherpa-DNS.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, Field


class Config(BaseModel):
    """Configuration for Sherpa-DNS."""

    # Source configuration
    label_prefix: str = "sherpa.dns"
    label_filter: str = ""

    # Provider configuration
    provider: str = "cloudflare"
    cloudflare_api_token: str = ""
    cloudflare_proxied_by_default: bool = False

    # Registry configuration
    registry: str = "txt"
    txt_prefix: str = "sherpa-dns-"
    txt_owner_id: str = "default"
    txt_wildcard_replacement: str = "star"
    encrypt_txt: bool = False
    encryption_key: Optional[str] = None

    # Controller configuration
    interval: str = "1m"
    once: bool = False
    dry_run: bool = False
    cleanup_on_stop: bool = True
    cleanup_delay: str = "15m"

    # Domain filtering
    domain_filter: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)

    # Logging configuration
    log_level: str = "info"

    @classmethod
    def from_yaml(cls, config_path: Optional[Union[str, Path]] = None) -> "Config":
        """
        Load configuration from a YAML file.

        Args:
            config_path: Path to the YAML configuration file

        Returns:
            Config: Config instance populated with values from the YAML file
        """
        # Default configuration paths to check
        default_paths = [
            Path("./sherpa-dns.yaml"),
            Path("./sherpa-dns.yml"),
            Path("/etc/sherpa-dns/sherpa-dns.yaml"),
            Path("/etc/sherpa-dns/config.yaml"),
        ]

        # If config_path is provided, use it
        if config_path:
            paths = [Path(config_path)]
        else:
            paths = default_paths

        # Try to load configuration from the first existing path
        config_data = {}
        for path in paths:
            if path.exists():
                with open(path, "r") as f:
                    yaml_content = f.read()
                    # Substitute environment variables
                    yaml_content = cls._substitute_env_vars(yaml_content)
                    config_data = yaml.safe_load(yaml_content)
                break

        # Flatten nested configuration
        flat_config = cls._flatten_config(config_data)

        # Create and return Config instance
        return cls(**flat_config)

    @staticmethod
    def _substitute_env_vars(content: str) -> str:
        """
        Substitute environment variables in the configuration content.

        Args:
            content: Configuration content

        Returns:
            str: Configuration content with environment variables substituted
        """
        # Pattern for ${ENV_VAR} or ${ENV_VAR:-default}
        pattern = r"\${([^}]+)}"

        def replace_env_var(match):
            env_var = match.group(1)
            if ":-" in env_var:
                env_var, default = env_var.split(":-", 1)
                return os.environ.get(env_var, default)
            return os.environ.get(env_var, "")

        return re.sub(pattern, replace_env_var, content)

    @staticmethod
    def _flatten_config(config_data: dict) -> dict:
        """
        Flatten nested configuration.

        Args:
            config_data: Nested configuration data

        Returns:
            dict: Flattened configuration data
        """
        flat_config = {}

        # Source configuration
        source = config_data.get("source", {})
        flat_config["label_prefix"] = source.get("label_prefix", "sherpa.dns")
        flat_config["label_filter"] = source.get("label_filter", "")

        # Provider configuration
        provider = config_data.get("provider", {})
        flat_config["provider"] = provider.get("name", "cloudflare")

        # Cloudflare provider configuration
        cloudflare = provider.get("cloudflare", {})
        flat_config["cloudflare_api_token"] = cloudflare.get("api_token", "")
        flat_config["cloudflare_proxied_by_default"] = cloudflare.get(
            "proxied_by_default", False
        )

        # Registry configuration
        registry = config_data.get("registry", {})
        flat_config["registry"] = registry.get("type", "txt")
        flat_config["txt_prefix"] = registry.get("txt_prefix", "sherpa-dns-")
        flat_config["txt_owner_id"] = registry.get("txt_owner_id", "default")
        flat_config["txt_wildcard_replacement"] = registry.get(
            "txt_wildcard_replacement", "star"
        )
        flat_config["encrypt_txt"] = registry.get("encrypt", False)
        flat_config["encryption_key"] = registry.get("encryption_key", None)

        # Controller configuration
        controller = config_data.get("controller", {})
        flat_config["interval"] = controller.get("interval", "1m")
        flat_config["once"] = controller.get("once", False)
        flat_config["dry_run"] = controller.get("dry_run", False)
        flat_config["cleanup_on_stop"] = controller.get("cleanup_on_stop", True)
        flat_config["cleanup_delay"] = controller.get("cleanup_delay", "15m")

        # Domain filtering
        domains = config_data.get("domains", {})
        flat_config["domain_filter"] = domains.get("include", [])
        flat_config["exclude_domains"] = domains.get("exclude", [])

        # Logging configuration
        logging = config_data.get("logging", {})
        flat_config["log_level"] = logging.get("level", "info")

        return flat_config

    def parse_duration(self, duration_str: str) -> int:
        """
        Parse a duration string like '15m' into seconds.

        Args:
            duration_str: Duration string

        Returns:
            int: Duration in seconds
        """
        if not duration_str:
            return 60  # Default to 1 minute

        # Pattern for duration string (e.g., 15m, 1h, 30s)
        pattern = r"^(\d+)([smhd])$"
        match = re.match(pattern, duration_str)

        if not match:
            return 60  # Default to 1 minute

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

        return 60  # Default to 1 minute
