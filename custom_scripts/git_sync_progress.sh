#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL="${1:?remote url required}"
MAX_ATTEMPTS="${2:-6}"
BRANCH="${GIT_SYNC_BRANCH:-main}"
PROXY_URL="${https_proxy:-${HTTPS_PROXY:-}}"
ORIGINAL_HTTP_PROXY="${HTTP_PROXY:-}"
ORIGINAL_HTTPS_PROXY="${HTTPS_PROXY:-}"
ORIGINAL_ALL_PROXY="${ALL_PROXY:-}"
ORIGINAL_LOWER_HTTP_PROXY="${http_proxy:-}"
ORIGINAL_LOWER_HTTPS_PROXY="${https_proxy:-}"
ORIGINAL_LOWER_ALL_PROXY="${all_proxy:-}"

clear_proxy() {
  git config --unset http.proxy 2>/dev/null || true
  git config --unset https.proxy 2>/dev/null || true
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
}

set_proxy() {
  if [ -n "$PROXY_URL" ]; then
    git config http.proxy "$PROXY_URL"
    git config https.proxy "$PROXY_URL"
    export HTTP_PROXY="${ORIGINAL_HTTP_PROXY:-$PROXY_URL}"
    export HTTPS_PROXY="${ORIGINAL_HTTPS_PROXY:-$PROXY_URL}"
    export http_proxy="${ORIGINAL_LOWER_HTTP_PROXY:-$PROXY_URL}"
    export https_proxy="${ORIGINAL_LOWER_HTTPS_PROXY:-$PROXY_URL}"
    if [ -n "$ORIGINAL_ALL_PROXY" ]; then
      export ALL_PROXY="$ORIGINAL_ALL_PROXY"
    fi
    if [ -n "$ORIGINAL_LOWER_ALL_PROXY" ]; then
      export all_proxy="$ORIGINAL_LOWER_ALL_PROXY"
    fi
    echo "[git-sync] use proxy: $PROXY_URL"
  else
    echo "[git-sync] no proxy configured"
  fi
}

rebase_in_progress() {
  [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]
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

  return 0
}

finish_rebase() {
  local guard=0
  while rebase_in_progress; do
    guard=$((guard + 1))
    if [ "$guard" -gt 20 ]; then
      echo "[git-sync] rebase recovery exceeded 20 iterations" >&2
      return 1
    fi

    if git status --porcelain 2>/dev/null | grep -q "^UU\|^AA\|^DD"; then
      resolve_rebase_conflicts || return 1
    elif ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
      git add -A
    fi

    if GIT_EDITOR=true git rebase --continue; then
      continue
    fi

    if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
      echo "[git-sync] current rebase commit is empty, running rebase --skip"
      GIT_EDITOR=true git rebase --skip || return 1
      continue
    fi

    return 1
  done
  return 0
}

print_git_failure() {
  local label="$1"
  local log_file="$2"
  echo "[git-sync] $label failed, last log lines:" >&2
  sed -E 's#https://[^/@]+(:[^/@]+)?@github.com/#https://***@github.com/#g' "$log_file" | tail -n 40 >&2 || true
}

run_git_with_log() {
  local label="$1"
  shift
  local log_file
  log_file="$(mktemp)"
  if "$@" >"$log_file" 2>&1; then
    rm -f "$log_file"
    return 0
  fi
  print_git_failure "$label" "$log_file"
  rm -f "$log_file"
  return 1
}

try_sync() {
  git stash push -m "sync-progress-stash-$(date +%s)" 2>/dev/null || true

  if run_git_with_log "fetch" git fetch --no-tags "$REMOTE_URL" "$BRANCH"; then
    if run_git_with_log "rebase" git rebase FETCH_HEAD; then
      if run_git_with_log "push" git push "$REMOTE_URL" "HEAD:$BRANCH"; then
        git stash pop 2>/dev/null || true
        echo "[git-sync] sync succeeded"
        return 0
      fi
    else
      echo "[git-sync] rebase failed"
    fi
  else
    echo "[git-sync] fetch failed"
  fi

  if rebase_in_progress; then
    finish_rebase || true
    if run_git_with_log "push after rebase recovery" git push "$REMOTE_URL" "HEAD:$BRANCH"; then
      git stash pop 2>/dev/null || true
      echo "[git-sync] sync succeeded after rebase recovery"
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
