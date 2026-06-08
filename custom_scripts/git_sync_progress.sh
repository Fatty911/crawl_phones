#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL="${1:?remote url required}"
MAX_ATTEMPTS="${2:-6}"
PROXY_URL="${https_proxy:-${HTTPS_PROXY:-}}"

clear_proxy() {
  git config --unset http.proxy 2>/dev/null || true
  git config --unset https.proxy 2>/dev/null || true
}

set_proxy() {
  if [ -n "$PROXY_URL" ]; then
    git config http.proxy "$PROXY_URL"
    git config https.proxy "$PROXY_URL"
    echo "[git-sync] use proxy: $PROXY_URL"
  else
    echo "[git-sync] no proxy configured"
  fi
}

resolve_rebase_conflicts() {
  local conflicts
  conflicts="$(git diff --name-only --diff-filter=U || true)"
  [ -n "$conflicts" ] || return 1

  echo "[git-sync] resolving progress conflicts"
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in
      zol/progress.json|pconline/progress.json)
        local ours theirs
        ours="$(mktemp)"
        theirs="$(mktemp)"
        git show ":2:$path" > "$ours" 2>/dev/null || echo "{}" > "$ours"
        git show ":3:$path" > "$theirs" 2>/dev/null || echo "{}" > "$theirs"
        python custom_scripts/merge_progress_json.py "$path" "$ours" "$theirs"
        rm -f "$ours" "$theirs"
        git add "$path"
        echo "[git-sync] merged $path"
        ;;
      *)
        echo "[git-sync] keeping remote version for non-progress conflict: $path"
        git checkout --theirs "$path" 2>/dev/null || true
        git add "$path" 2>/dev/null || true
        ;;
    esac
  done <<< "$conflicts"

  if ! GIT_EDITOR=true git rebase --continue 2>/dev/null; then
    if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
      GIT_EDITOR=true git rebase --skip 2>/dev/null
    else
      return 1
    fi
  fi
}

try_sync() {
  git stash push -m "sync-progress-stash-$(date +%s)" 2>/dev/null || true

  if git pull --rebase "$REMOTE_URL" main 2>/dev/null; then
    if git push "$REMOTE_URL" HEAD:main 2>/dev/null; then
      git stash pop 2>/dev/null || true
      echo "[git-sync] sync succeeded"
      return 0
    fi
    echo "[git-sync] push failed"
  else
    echo "[git-sync] pull --rebase failed"
  fi

  if git status --porcelain 2>/dev/null | grep -q "^UU\|^AA\|^DD"; then
    resolve_rebase_conflicts || true
    if git push "$REMOTE_URL" HEAD:main 2>/dev/null; then
      git stash pop 2>/dev/null || true
      echo "[git-sync] sync succeeded after conflict resolution"
      return 0
    fi
  fi

  git rebase --abort 2>/dev/null || true
  git stash pop 2>/dev/null || true
  return 1
}

echo "[git-sync] start sync, attempts=$MAX_ATTEMPTS"
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "[git-sync] attempt $attempt/$MAX_ATTEMPTS"
  if [ $((attempt % 2)) -eq 1 ] && [ -n "$PROXY_URL" ]; then
    set_proxy
  else
    clear_proxy
    echo "[git-sync] direct connection"
  fi

  if try_sync; then
    clear_proxy
    exit 0
  fi

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    wait_seconds=$((RANDOM % 10 + 5))
    echo "[git-sync] retry after ${wait_seconds}s"
    sleep "$wait_seconds"
  fi
done

clear_proxy
echo "[git-sync] failed after $MAX_ATTEMPTS attempts" >&2
exit 1
