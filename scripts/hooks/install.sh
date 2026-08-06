#!/usr/bin/env bash
# Install the repo's git hooks. Run once after cloning.
set -euo pipefail
cd "$(dirname "$0")/../.."
git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/pre-commit
echo "✓ hooks installed (core.hooksPath = scripts/hooks)"
echo "  direct commits to staging/main/master will now be refused"
