#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Automatic AWS deployment is disabled.

The legacy script created unapproved secrets and applied an obsolete
Lambda/Snowflake/market architecture. It is intentionally fail-closed.

Read terraform/README.md and complete the authenticated AWS preflight, region,
budget, notification-email, access-mode, networking, and GitHub OIDC gates.
Then run reviewed Terraform init/plan commands manually. This script never
executes terraform apply.
EOF

exit 2
