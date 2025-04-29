"""
Controller module for Sherpa-DNS.

This module is responsible for coordinating between the source, registry, and provider
components to ensure that the desired state is maintained.
"""

import asyncio
import logging
from typing import Optional

from sherpa_dns.cleanup_tracker import CleanupTracker
from sherpa_dns.plan import Plan


class Controller:
    """
    Controller that coordinates between the source, registry, and provider components.
    """

    def __init__(
        self,
        source,
        registry,
        provider,
        interval: str = "1m",
        cleanup_delay: str = "15m",
        cleanup_on_stop: bool = True,
    ):
        """
        Initialize a Controller.

        Args:
            source: Source component
            registry: Registry component
            provider: Provider component
            interval: Reconciliation interval
            cleanup_delay: Delay before cleaning up DNS records for stopped containers
            cleanup_on_stop: Whether to clean up DNS records for stopped containers
        """
        self.source = source
        self.registry = registry
        self.provider = provider
        self.interval = self._parse_interval(interval)
        self.cleanup_on_stop = cleanup_on_stop
        self.cleanup_tracker = CleanupTracker(cleanup_delay)
        self.logger = logging.getLogger("sherpa-dns.controller")
        self._event_triggered_reconcile_task: Optional[
            asyncio.Task
        ] = None  # Task for debouncing
        self._debounce_delay = 2  # Seconds to wait after an event before reconciling

    async def run_reconciliation_loop(self) -> None:
        """
        Runs the controller's reconciliation loop at the specified interval.
        """
        # Log at DEBUG as the main task start is logged in __main__
        self.logger.debug(
            f"Reconciliation loop starting with interval {self.interval} seconds"
        )

        while True:
            try:
                await self.run_once()
            except Exception as e:
                self.logger.error(f"Error in reconciliation loop: {e}")

            await asyncio.sleep(self.interval)

    async def run_once(self) -> None:
        """
        Performs a single reconciliation run.
        """

        try:
            # Get desired endpoints from source
            desired_endpoints = await self.source.endpoints()

            # Get current endpoints from registry
            current_endpoints = await self.registry.records()

            # Calculate plan first to know if changes are pending
            plan = Plan(
                current_endpoints, desired_endpoints, policy="sync"
            ).calculate_changes()
            potential_deletes = {ep.id: ep for ep in plan.delete}
            # Base pending changes ONLY on creates/updates, as deletes are handled by tracker
            has_pending_changes = bool(plan.create or plan.update_old)

            # Log summary - use DEBUG level if system is stable (no immediate changes)
            log_level = logging.DEBUG if not has_pending_changes else logging.INFO

            self.logger.log(
                log_level,
                f"Running reconciliation: Found {len(desired_endpoints)} desired and "
                f"{len(current_endpoints)} current endpoints.",
            )

            if potential_deletes and self.cleanup_on_stop:
                for endpoint_id, endpoint in potential_deletes.items():
                    # Mark these endpoints for future deletion using the tracker
                    self.cleanup_tracker.mark_for_deletion(endpoint_id)
                    self.logger.debug(
                        f"Ensured endpoint {endpoint_id} ({endpoint.dnsname}) is marked for delayed cleanup."
                    )

                # IMPORTANT: Clear the delete list from the plan that gets synced immediately
                plan.delete = []
            elif potential_deletes:  # cleanup_on_stop is False
                self.logger.info(
                    f"Identified {len(potential_deletes)} endpoints not in desired state, but cleanup_on_stop=False. Ignoring."
                )
                # Clear deletes from the plan as we don't delete on stop
                plan.delete = []

            # ---- End Deletion Handling Modification ----

            # Apply ONLY creates and updates now
            # plan.delete is now always empty here
            if plan.has_changes():
                # Adjust log message as plan.delete is now empty
                self.logger.info(
                    f"Applying changes: {len(plan.create)} creates, {len(plan.update_old)} updates"
                )
                await self.registry.sync(plan)  # Syncs only creates/updates
            else:
                self.logger.debug("No immediate changes (creates/updates) to apply")

            # Process cleanup tracker (this handles the actual deletions after delay)
            await self.process_cleanup()
        except Exception as e:
            self.logger.error(
                f"Error in reconciliation: {e}", exc_info=True
            )  # Add exc_info for better debugging

    async def process_cleanup(self) -> None:
        """
        Process the cleanup tracker to handle delayed deletions.
        """
        if not self.cleanup_on_stop:
            self.logger.debug("Cleanup on stop is disabled, skipping cleanup process.")
            return

        # Log status of pending deletions
        try:
            pending_status = self.cleanup_tracker.get_pending_status()
            if pending_status:
                self.logger.debug(
                    f"Checking status of {len(pending_status)} endpoints pending deletion:"
                )
                for endpoint_id, remaining_time in pending_status.items():
                    if remaining_time > 0:
                        self.logger.debug(
                            f"  - Endpoint ID {endpoint_id} will be eligible for deletion in {remaining_time:.1f} seconds."
                        )
                    else:
                        # This case should be rare as get_eligible_for_deletion usually handles it first
                        self.logger.debug(
                            f"  - Endpoint ID {endpoint_id} is overdue for deletion by {-remaining_time:.1f} seconds."
                        )
            else:
                self.logger.debug("No endpoints currently pending deletion.")
        except Exception as e:
            self.logger.error(
                f"Error getting pending cleanup status: {e}", exc_info=True
            )
            # Continue with eligibility check anyway

        # Get endpoints eligible for deletion
        try:
            eligible_ids = self.cleanup_tracker.get_eligible_for_deletion()

            if not eligible_ids:
                self.logger.debug("No endpoints eligible for deletion currently.")
                return

            self.logger.debug(
                f"Found {len(eligible_ids)} endpoints eligible for deletion by tracker."
            )

            # Get current endpoints - needed to construct deletion plan
            current_endpoints = await self.registry.records()
            current_endpoints_map = {ep.id: ep for ep in current_endpoints}

            # Filter endpoints eligible for deletion that still exist
            endpoints_to_delete = []
            for endpoint_id in eligible_ids:
                if endpoint_id in current_endpoints_map:
                    endpoints_to_delete.append(current_endpoints_map[endpoint_id])
                else:
                    self.logger.warning(
                        f"Endpoint ID {endpoint_id} marked for deletion, but not found in current records. Already deleted?"
                    )

            if endpoints_to_delete:
                # Create a deletion plan
                deletion_plan = Plan.deletion_only(endpoints_to_delete)

                # Apply changes
                self.logger.debug(
                    f"Applying deletion plan for {len(endpoints_to_delete)} endpoints after cleanup delay"
                )
                await self.registry.sync(deletion_plan)
            else:
                self.logger.debug(
                    "No existing endpoints matched the eligible IDs for deletion."
                )

        except Exception as e:
            self.logger.error(f"Error during cleanup processing: {e}", exc_info=True)

    async def process_event(self, event: dict) -> None:
        """
        Process a Docker event and trigger reconciliation if needed.
        Relies on run_once() to handle marking/unmarking based on state diff,
        but attempts to unmark quickly on 'start' events.

        Args:
            event: Docker event
        """
        event_type = event.get("status")
        container_id = event.get("id")
        container_short_id = container_id[:12] if container_id else "N/A"

        if not container_id:
            self.logger.warning("Received event with no container ID.")
            return

        if event_type in ["die", "stop", "kill"]:
            # Container stopped. run_once() will detect it missing and mark via cleanup_tracker.
            # Log at DEBUG level to reduce noise from multiple stop-related events
            self.logger.debug(
                f"Container {container_short_id} stopped event ({event_type}) received."
            )
        elif event_type == "start":
            # Container started. run_once() will ensure it's created/updated.
            # Log at DEBUG level, actual reconciliation scheduling logged later at INFO
            self.logger.debug(f"Container {container_short_id} started event received.")
            try:
                # Fetch desired state to find the endpoints associated with this container
                desired_endpoints = await self.source.endpoints()  # Fetch fresh state
                container_endpoints = [
                    endpoint
                    for endpoint in desired_endpoints
                    if endpoint.container_id == container_id
                ]
                if container_endpoints:
                    self.logger.debug(
                        f"Unmarking {len(container_endpoints)} endpoints for started container {container_short_id}"
                    )
                    for endpoint in container_endpoints:
                        # Tell tracker this endpoint is active again
                        self.cleanup_tracker.unmark_for_deletion(endpoint.id)
                else:
                    self.logger.debug(
                        f"No desired endpoints found for started container {container_short_id} to unmark (might lack labels?)."
                    )
            except Exception as e:
                self.logger.error(
                    f"Error fetching desired endpoints during start event processing for {container_short_id}: {e}",
                    exc_info=True,
                )
        else:
            self.logger.debug(
                f"Ignoring Docker event type '{event_type}' for container {container_short_id}"
            )
            return  # Don't reconcile on ignored events

        # --- Debounce Reconciliation Trigger ---
        if (
            self._event_triggered_reconcile_task
            and not self._event_triggered_reconcile_task.done()
        ):
            self.logger.debug(
                f"Reconciliation already scheduled/running due to a recent event. "
                f"Debouncing trigger from event '{event_type}' for container {container_short_id}."
            )
            return

        # Schedule the debounced reconciliation
        # This log remains INFO as it indicates a reconciliation WILL be scheduled
        self.logger.info(
            f"Scheduling reconciliation due to event '{event_type}' for container {container_short_id} (after {self._debounce_delay}s delay)"
        )
        self._event_triggered_reconcile_task = asyncio.create_task(
            self._run_once_debounced()
        )
        # Add a callback to clear the task variable once it's done (optional, helps cleanup)
        # self._event_triggered_reconcile_task.add_done_callback(lambda _: setattr(self, '_event_triggered_reconcile_task', None))

        # Note: We no longer call self.run_once() directly here.
        # await self.run_once()

    async def _run_once_debounced(self):
        """Runs run_once after a short delay to allow debouncing.
        Clears the tracking task variable upon completion.
        """
        try:
            await asyncio.sleep(self._debounce_delay)
            self.logger.debug(
                "Running event-triggered reconciliation after debounce delay."
            )
            await self.run_once()
        except asyncio.CancelledError:
            self.logger.debug("Debounced reconciliation task cancelled.")
        except Exception as e:
            self.logger.error(
                f"Error during debounced reconciliation run: {e}", exc_info=True
            )
        # Task is finished, future checks in process_event will see it as done.

    async def run_cleanup_tracker(self) -> None:
        """
        Run the cleanup tracker's background processing.
        """
        self.logger.debug("Cleanup tracker task started.")

        while True:
            try:
                await self.process_cleanup()
            except Exception as e:
                self.logger.error(f"Error in cleanup tracker: {e}")

            await asyncio.sleep(60)  # Check every minute

    async def watch_events(self) -> None:
        """
        Watch for Docker events and process them.
        """
        self.logger.debug("Controller event watcher task started.")

        while True:
            try:
                # Get event from queue
                event = await self.source.event_queue.get()

                # Process event
                await self.process_event(event)

                # Mark task as done
                self.source.event_queue.task_done()
            except Exception as e:
                self.logger.error(f"Error processing event: {e}")

    @staticmethod
    def _parse_interval(interval: str) -> int:
        """
        Parse an interval string like '1m' into seconds.

        Args:
            interval: Interval string

        Returns:
            int: Interval in seconds
        """
        if not interval:
            return 60  # Default to 1 minute

        # Pattern for interval string (e.g., 1m, 5s, 1h)
        if interval.endswith("s"):
            return int(interval[:-1])
        elif interval.endswith("m"):
            return int(interval[:-1]) * 60
        elif interval.endswith("h"):
            return int(interval[:-1]) * 60 * 60
        elif interval.endswith("d"):
            return int(interval[:-1]) * 60 * 60 * 24

        # If no unit is specified, assume seconds
        try:
            return int(interval)
        except ValueError:
            return 60  # Default to 1 minute
