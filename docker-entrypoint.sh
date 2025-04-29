#!/bin/sh
set -e

# Only show verbose entrypoint logs if SHERPA_ENTRYPOINT_DEBUG is true
if [ "$SHERPA_ENTRYPOINT_DEBUG" = "true" ]; then
  echo "Entrypoint (Debug): Checking docker socket permissions..."
fi

# Check if the socket exists first
if [ ! -S /var/run/docker.sock ]; then
  echo "Error: Docker socket /var/run/docker.sock not found!"
  # Consider exiting if the socket is absolutely required:
  # exit 1
else
  # Attempt to get GID using standard Linux stat command format
  # Capture output/error, check exit status
  DOCKER_GID_OUTPUT=$(stat -c '%g' /var/run/docker.sock 2>&1)
  DOCKER_GID_RET=$?

  # Check if stat command succeeded and output is numeric
  if [ "$DOCKER_GID_RET" -eq 0 ] && echo "$DOCKER_GID_OUTPUT" | grep -Eq '^[0-9]+$'; then
      DOCKER_GID_NUM="$DOCKER_GID_OUTPUT"
      if [ "$SHERPA_ENTRYPOINT_DEBUG" = "true" ]; then
        echo "Entrypoint (Debug): Detected Docker socket GID: $DOCKER_GID_NUM"
      fi

      if [ "$DOCKER_GID_NUM" -eq 0 ]; then
          if [ "$SHERPA_ENTRYPOINT_DEBUG" = "true" ]; then
            echo "Entrypoint (Debug): Docker socket GID is 0 (root group). Adding 'sherpa' user to root group."
          fi
          # Add sherpa user to the root group (GID 0). Use -aG to append.
          usermod -aG root sherpa || usermod -aG 0 sherpa || echo "Warning: Failed to add sherpa to root group (GID 0)."
      else
          # GID is non-zero (e.g., 20)
          TARGET_GROUP_NAME=""
          # Check if a group already exists with this GID
          if getent group "$DOCKER_GID_NUM" > /dev/null; then
              # Group exists, find its name
              TARGET_GROUP_NAME=$(getent group "$DOCKER_GID_NUM" | cut -d: -f1)
              if [ "$SHERPA_ENTRYPOINT_DEBUG" = "true" ]; then
                echo "Entrypoint (Debug): Group with GID $DOCKER_GID_NUM ('$TARGET_GROUP_NAME') already exists. Adding 'sherpa' to this group."
              fi
          else
              # Group doesn't exist, create one with a specific name
              TARGET_GROUP_NAME="docker_socket_access" # Use a consistent, specific name
              if [ "$SHERPA_ENTRYPOINT_DEBUG" = "true" ]; then
                echo "Entrypoint (Debug): No group with GID $DOCKER_GID_NUM found. Creating group '$TARGET_GROUP_NAME'."
              fi
              # Create group; -f handles edge cases but might not be needed if checked first
              groupadd -g "$DOCKER_GID_NUM" "$TARGET_GROUP_NAME" || echo "Warning: Could not create group '$TARGET_GROUP_NAME' with GID $DOCKER_GID_NUM."
          fi

          # Add the sherpa user to the determined TARGET_GROUP_NAME (handle potential failure)
          if [ -n "$TARGET_GROUP_NAME" ]; then
              usermod -aG "$TARGET_GROUP_NAME" sherpa || echo "Warning: Failed to add sherpa to group '$TARGET_GROUP_NAME' (GID $DOCKER_GID_NUM)."
          else
              echo "Warning: Could not determine or create target group for GID $DOCKER_GID_NUM."
          fi
      fi
  else
      # stat command failed or output wasn't numeric
      # Keep this warning visible even without debug, as it indicates a potential problem
      echo "Warning: Could not determine numeric GID of /var/run/docker.sock using 'stat -c %g'."
      echo "         'stat' exit code: $DOCKER_GID_RET, output: '$DOCKER_GID_OUTPUT'."
      echo "         Please ensure 'coreutils' (providing 'stat') is installed in the image."
      echo "         Proceeding without modifying 'sherpa' user's groups."
  fi
fi

if [ "$SHERPA_ENTRYPOINT_DEBUG" = "true" ]; then
  echo "Entrypoint (Debug): Current groups for 'sherpa': $(id sherpa)"
  echo "Entrypoint (Debug): Attempting to execute command as user 'sherpa': $@"
fi
# Drop privileges and execute the command passed to the script (the CMD)
echo "Entrypoint: Executing command as user 'sherpa': $@"
exec gosu sherpa "$@"
