#!/bin/sh
# Container start-up: run the world as the user/group given by PUID/PGID
# (like linuxserver.io images), so files in your data and config folders are
# owned by you, not root. TZ sets the container's time zone for log times.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    # Make sure a group and user with those ids exist inside the container.
    if ! getent group "$PGID" >/dev/null; then
        groupadd -o -g "$PGID" world
    fi
    if ! getent passwd "$PUID" >/dev/null; then
        useradd -o -u "$PUID" -g "$PGID" -M -d /app -s /usr/sbin/nologin world
    fi
    mkdir -p /app/data /app/config
    # Hand the folders over (only if needed — big worlds take a while to chown).
    for dir in /app/data /app/config; do
        if [ "$(stat -c %u:%g "$dir")" != "$PUID:$PGID" ] || \
           [ -n "$(find "$dir" \( ! -user "$PUID" -o ! -group "$PGID" \) -print -quit 2>/dev/null)" ]; then
            echo "[entrypoint] giving $dir to $PUID:$PGID"
            chown -R "$PUID:$PGID" "$dir"
        fi
    done
    echo "[entrypoint] starting as uid $PUID, gid $PGID, TZ=${TZ:-UTC}"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
