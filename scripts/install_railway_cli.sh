#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_PATH:?GITHUB_PATH is required}"
cli_dir="$RUNNER_TEMP/aura-railway-cli"
mkdir -p "$cli_dir"
archive="$cli_dir/railway.tar.gz"
asset='repos/railwayapp/cli/releases/assets/462501869'

# Use the authenticated GitHub client already used by the release gate.
# Keep the same official Linux 5.23.3 asset and verify before execution.
if ! timeout 90 gh api "$asset" --header 'Accept: application/octet-stream' > "$archive"; then
  curl --http1.1 --fail --silent --show-error --location --retry 2 --retry-all-errors \
    --connect-timeout 15 --max-time 60 \
    'https://github.com/railwayapp/cli/releases/download/v5.23.3/railway-v5.23.3-x86_64-unknown-linux-gnu.tar.gz' \
    --output "$archive"
fi
echo "79622bd63fdae79709bba016b892ae61f89c5645fa47e65d2e4f60c21d7e0949  $archive" | sha256sum --check --strict
tar --extract --gzip --file "$archive" --directory "$cli_dir" railway
chmod 755 "$cli_dir/railway"
"$cli_dir/railway" --version
echo "$cli_dir" >> "$GITHUB_PATH"
