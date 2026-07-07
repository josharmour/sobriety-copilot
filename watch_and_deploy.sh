#!/bin/bash

# Simple directory watcher that triggers deploy.sh on modifications
WATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAST_MD5=""

get_md5() {
    # Find all python, html, css, js, yml files and get their md5 checksum
    find "$WATCH_DIR/src" "$WATCH_DIR/static" "$WATCH_DIR/nginx" -type f \( -name "*.py" -o -name "*.html" -o -name "*.css" -o -name "*.js" -o -name "*.yml" -o -name "*.yaml" \) -exec md5sum {} + 2>/dev/null | md5sum | awk '{print $1}'
}

echo "Starting deployment watcher for $WATCH_DIR..."
echo "Deploys to NAS will trigger automatically on file changes."

# Initial checksum
LAST_MD5=$(get_md5)

while true; do
    sleep 3
    CURRENT_MD5=$(get_md5)
    if [ "$CURRENT_MD5" != "$LAST_MD5" ]; then
        echo "Change detected! Waiting 3 seconds for write operations to settle..."
        sleep 3
        
        # Debounce/verify if changes are still happening
        CHECK_MD5=$(get_md5)
        if [ "$CHECK_MD5" = "$CURRENT_MD5" ]; then
            echo "Triggering deployment..."
            if ./deploy.sh; then
                LAST_MD5=$CURRENT_MD5
                echo "Deploy succeeded! Monitoring for new changes..."
            else
                echo "Deploy failed. Will retry on next file change."
            fi
        fi
    fi
done
