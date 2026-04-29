#!/usr/bin/env bash
# Bootstrap or manage admin users on the production droplet.
#
# Auto-detects the running blue or green container and execs the Python
# promotion script inside it. No docker-compose knowledge required at the
# call site.
#
# Usage:
#     ./promote-admin <email>           # grant admin
#     ./promote-admin <email> --revoke  # revoke admin

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <email> [--revoke]" >&2
    exit 2
fi

CONTAINER=""
for color in blue green; do
    name="bedlam-connect-$color"
    if [ -n "$(docker ps --format '{{.Names}}' --filter "name=^${name}$")" ]; then
        CONTAINER="$name"
        break
    fi
done

if [ -z "$CONTAINER" ]; then
    echo "❌ No running bedlam-connect container found." >&2
    echo "   Looked for: bedlam-connect-blue, bedlam-connect-green" >&2
    echo "   Currently running:" >&2
    docker ps --format 'table {{.Names}}\t{{.Status}}' >&2
    exit 1
fi

echo "🔧 Running promote_admin against $CONTAINER..."
exec docker exec "$CONTAINER" python scripts/dev/promote_admin.py "$@"
