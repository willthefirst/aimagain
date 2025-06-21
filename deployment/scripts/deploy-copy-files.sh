#!/bin/bash

# Manual SCP script to copy deployment files to droplet
# This replaces the appleboy/scp-action@v0.1.7 step in GitHub Actions

set -e

# Configuration - can be overridden by environment variables
DROPLET_HOST="${DROPLET_HOST:-}"
DROPLET_USERNAME="${DROPLET_USERNAME:-}"
DROPLET_SSH_KEY_PATH="${DROPLET_SSH_KEY_PATH:-}"

# Source and target paths
SOURCE_DIR="deployment/droplet-files"
TARGET_DIR="/opt/aimagain/deployment"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Copy deployment files to droplet using SCP"
    echo ""
    echo "Options:"
    echo "  -h, --host HOST              Droplet host (can also use DROPLET_HOST env var)"
    echo "  -u, --username USERNAME      SSH username (can also use DROPLET_USERNAME env var)"
    echo "  -k, --key-path PATH         SSH private key path (can also use DROPLET_SSH_KEY_PATH env var)"
    echo "  --help                      Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  DROPLET_HOST                Droplet host"
    echo "  DROPLET_USERNAME            SSH username"
    echo "  DROPLET_SSH_KEY_PATH        Path to SSH private key file"
    echo ""
    echo "Examples:"
    echo "  $0 --host 192.168.1.100 --username deploy --key-path ~/.ssh/deploy_key"
    echo "  DROPLET_HOST=192.168.1.100 DROPLET_USERNAME=deploy DROPLET_SSH_KEY_PATH=~/.ssh/deploy_key $0"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            DROPLET_HOST="$2"
            shift 2
            ;;
        -u|--username)
            DROPLET_USERNAME="$2"
            shift 2
            ;;
        -k|--key-path)
            DROPLET_SSH_KEY_PATH="$2"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$DROPLET_HOST" ]]; then
    log_error "DROPLET_HOST is required. Set it via environment variable or --host flag."
    usage
    exit 1
fi

if [[ -z "$DROPLET_USERNAME" ]]; then
    log_error "DROPLET_USERNAME is required. Set it via environment variable or --username flag."
    usage
    exit 1
fi

if [[ -z "$DROPLET_SSH_KEY_PATH" ]]; then
    log_error "DROPLET_SSH_KEY_PATH is required. Set it via environment variable or --key-path flag."
    usage
    exit 1
fi

# Validate source directory exists
if [[ ! -d "$SOURCE_DIR" ]]; then
    log_error "Source directory '$SOURCE_DIR' does not exist!"
    exit 1
fi

# Expand tilde in SSH key path
DROPLET_SSH_KEY_PATH="${DROPLET_SSH_KEY_PATH/#\~/$HOME}"

# Validate SSH key exists
if [[ ! -f "$DROPLET_SSH_KEY_PATH" ]]; then
    log_error "SSH key file '$DROPLET_SSH_KEY_PATH' does not exist!"
    exit 1
fi

# Check SSH key permissions
KEY_PERMS=$(stat -c "%a" "$DROPLET_SSH_KEY_PATH" 2>/dev/null || stat -f "%A" "$DROPLET_SSH_KEY_PATH" 2>/dev/null || echo "unknown")
if [[ "$KEY_PERMS" != "600" ]]; then
    log_warn "SSH key permissions are '$KEY_PERMS', should be '600' for security"
    log_info "Fixing SSH key permissions..."
    chmod 600 "$DROPLET_SSH_KEY_PATH"
fi

log_info "Starting deployment file copy..."
log_info "Source: $SOURCE_DIR"
log_info "Target: $DROPLET_USERNAME@$DROPLET_HOST:$TARGET_DIR"
log_info "SSH Key: $DROPLET_SSH_KEY_PATH"

# SSH options for non-interactive operation
SSH_OPTS="-i $DROPLET_SSH_KEY_PATH -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

# Create target directory on remote host
log_info "Creating target directory on remote host..."
ssh $SSH_OPTS "$DROPLET_USERNAME@$DROPLET_HOST" "mkdir -p $TARGET_DIR"

# Copy files (equivalent to strip_components: 2 from the original action)
# This copies the contents of droplet-files directory directly to the target
log_info "Copying deployment files..."
scp $SSH_OPTS -r "$SOURCE_DIR"/* "$DROPLET_USERNAME@$DROPLET_HOST:$TARGET_DIR/"

if [[ $? -eq 0 ]]; then
    log_info "✅ Deployment files copied successfully!"
else
    log_error "❌ Failed to copy deployment files!"
    exit 1
fi

# Verify files were copied
log_info "Verifying copied files..."
ssh $SSH_OPTS "$DROPLET_USERNAME@$DROPLET_HOST" "ls -la $TARGET_DIR"

log_info "🎉 Deployment file copy completed successfully!"
