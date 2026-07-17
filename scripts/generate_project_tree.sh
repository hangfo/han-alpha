#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary="$(mktemp)"
trap 'rm -f "$temporary"' EXIT

cd "$repo_root"
git ls-files --cached --others --exclude-standard \
  | while IFS= read -r path; do
      if test -e "$path"; then
        printf './%s\n' "$path"
      fi
    done \
  | LC_ALL=C sort > "$temporary"
mv "$temporary" PROJECT_TREE.txt
trap - EXIT
