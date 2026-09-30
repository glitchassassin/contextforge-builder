#!/usr/bin/env bash
set -euo pipefail
source_dir=${1:?Usage: apply-patches.sh UPSTREAM_DIR}
builder_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [ -n "$(git -C "$source_dir" status --porcelain --untracked-files=no)" ]; then
  echo "Refusing to patch a modified upstream checkout" >&2
  exit 1
fi
for patch_file in "$builder_dir"/patches/*.patch; do
  # No fuzzy application or automatic reverse-patch skip: upstream changes need review.
  git -C "$source_dir" apply --check "$patch_file"
  git -C "$source_dir" apply "$patch_file"
done
git -C "$source_dir" diff --check
echo "Applied ContextForge compatibility patches"
