"""
Health check module for Sherpa-DNS.

This module provides health check endpoints for monitoring the application.
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import docker


class HealthCheckHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for health check endpoints.
    """

    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger("sherpa-dns.health")
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """
        Handle GET requests.
        """
        if self.path == "/health":
            self._handle_health_check()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def _handle_health_check(self):
        """
        Handle health check requests.
        """
        # Check Docker connection
        try:
            docker_client = docker.from_env()
            docker_client.ping()

            # Return 200 OK
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            response = {"status": "healthy", "docker": "connected"}

            self.wfile.write(json.dumps(response).encode())
        except Exception as e:
            # Return 503 Service Unavailable
            self.send_response(503)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            response = {"status": "unhealthy", "docker": f"error: {str(e)}"}

            self.wfile.write(json.dumps(response).encode())

    def _handle_metrics(self):
        """
        Handle metrics requests.
        """
        # Return 200 OK
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

        # Simple metrics
        metrics = [
            "# HELP sherpa_dns_up Whether the Sherpa-DNS service is up",
            "# TYPE sherpa_dns_up gauge",
            "sherpa_dns_up 1",
        ]

        self.wfile.write("\n".join(metrics).encode())

    def log_message(self, format, *args):
        """
        Override log_message to use the application logger.
        """
        self.logger.debug(format % args)


class HealthCheckServer:
    """
    HTTP server for health check endpoints.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        """
        Initialize a HealthCheckServer.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self.logger = logging.getLogger("sherpa-dns.health")

    def start(self):
        """
        Start the health check server.
        """
        self.server = HTTPServer((self.host, self.port), HealthCheckHandler)
        self.thread = Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        self.logger.info(f"Health check: {self.host}:{self.port}/health")

    def stop(self):
        """
        Stop the health check server.
        """
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.logger.info("Health check server stopped")
