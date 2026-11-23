#!/usr/bin/env bash
# Usage: scripts/create_user.sh <user-pool-id> <email> [tenant-id]
# Creates an invited Cognito user (temporary password is emailed). tenant-id is set by admins only.
set -euo pipefail
aws cognito-idp admin-create-user --user-pool-id "$1" --username "$2" \
  --user-attributes Name=email,Value="$2" Name=email_verified,Value=true Name=custom:tenant_id,Value="${3:-default}" \
  --desired-delivery-mediums EMAIL
