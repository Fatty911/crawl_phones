#!/usr/bin/env python3
"""Calculate crawler run windows and safe runtime budgets for GitHub Actions."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


WINDOWS = {
    "morning": (8 * 60, 12 * 60 + 30),
    "afternoon": (13 * 60, 22 * 60),
}
MIN_RUN_SECONDS = 300


def append_line(path: str | None, line: str) -> None:
    if path:
        with Path(path).open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def cn_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def seconds_since_midnight(now: datetime) -> int:
    return now.hour * 3600 + now.minute * 60 + now.second


def minutes_since_midnight(now: datetime) -> int:
    return now.hour * 60 + now.minute


def resolve_profile(profile: str, now: datetime) -> str | None:
    if profile and profile != "auto":
        return profile
    current = minutes_since_midnight(now)
    for name, (start, end) in WINDOWS.items():
        if start <= current <= end:
            return name
    return None


def window_safe_remain(profile: str, now: datetime, buffer_seconds: int) -> int:
    _start, end_minutes = WINDOWS[profile]
    return end_minutes * 60 - seconds_since_midnight(now) - buffer_seconds


def configure(args: argparse.Namespace) -> int:
    now = cn_now()
    requested = args.schedule_profile or args.profile or "auto"
    profile = resolve_profile(requested, now)
    if profile not in WINDOWS:
        print(
            f"Current Beijing time {now:%H:%M:%S} is outside crawl windows "
            "(08:00-12:30 or 13:00-22:00); skipping."
        )
        append_line(args.github_output, "skip=true")
        return 0

    run_seconds = args.morning_run_time if profile == "morning" else args.afternoon_run_time
    safe_remain = window_safe_remain(profile, now, args.window_end_buffer_seconds)
    if safe_remain < MIN_RUN_SECONDS:
        print(
            f"Only {safe_remain}s remain before the {profile} window safety cutoff; skipping."
        )
        append_line(args.github_output, "skip=true")
        return 0
    if safe_remain < run_seconds:
        print(
            f"RUN_TIME reduced from {run_seconds}s to {safe_remain}s "
            f"to leave {args.window_end_buffer_seconds}s before the {profile} window ends."
        )
        run_seconds = safe_remain

    append_line(args.github_env, f"RUN_PROFILE={profile}")
    append_line(args.github_env, f"RUN_TIME={run_seconds}")
    append_line(args.github_output, "skip=false")
    print(f"Profile={profile}, RUN_TIME={run_seconds}s, Beijing time={now:%H:%M:%S}")
    return 0


def clamp(args: argparse.Namespace) -> int:
    # 调试模式：跳过时间窗口检查，并显式设置跳过标志为false
    debug_mode = os.environ.get("DEBUG_MODE", os.environ.get("debug_mode", "false"))
    if str(debug_mode).lower() in ("true", "1", "yes"):
        print(f"调试模式：跳过 {args.step_label} 时间预算检查")
        # 显式设置跳过标志为false，防止后续步骤被误跳过
        append_line(args.github_env, f"{args.skip_env}=false")
        print(f"已设置 {args.skip_env}=false")
        return 0

    now = cn_now()
    run_time = int(os.environ.get("RUN_TIME", "0") or "0")
    profile = os.environ.get("RUN_PROFILE", "auto")
    workflow_start = int(os.environ.get("WORKFLOW_START_EPOCH", "0") or "0")
    max_workflow = int(os.environ.get("MAX_WORKFLOW_SECONDS", "21600") or "21600")
    progress_buffer = int(
        os.environ.get("PROGRESS_COMMIT_BUFFER_SECONDS", str(args.progress_buffer_seconds))
        or str(args.progress_buffer_seconds)
    )
    current_epoch = int(time.time())
    elapsed = max(0, current_epoch - workflow_start) if workflow_start else 0
    action_safe = max_workflow - elapsed - progress_buffer

    if profile not in WINDOWS:
        profile = resolve_profile(profile, now) or ""
    window_safe = (
        window_safe_remain(profile, now, args.window_end_buffer_seconds)
        if profile in WINDOWS
        else action_safe
    )
    safe_remain = min(action_safe, window_safe)
    print(
        f"{args.step_label}: elapsed={elapsed}s, action_safe={action_safe}s, "
        f"window_safe={window_safe}s, requested RUN_TIME={run_time}s"
    )

    if safe_remain < MIN_RUN_SECONDS:
        print(
            f"Safe remaining time is {safe_remain}s; skipping {args.step_label} "
            "to avoid losing progress."
        )
        append_line(args.github_env, f"{args.skip_env}=true")
        return 0

    if run_time <= 0 or safe_remain < run_time:
        print(f"RUN_TIME reduced from {run_time}s to {safe_remain}s by combined budget.")
        append_line(args.github_env, f"RUN_TIME={safe_remain}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure_parser = subparsers.add_parser("configure")
    configure_parser.add_argument("--profile", default=os.environ.get("PROFILE_INPUT", "auto"))
    configure_parser.add_argument("--schedule-profile", default=os.environ.get("SCHEDULE_PROFILE", ""))
    configure_parser.add_argument("--morning-run-time", type=int, default=int(os.environ.get("MORNING_RUN_TIME", "10800")))
    configure_parser.add_argument("--afternoon-run-time", type=int, default=int(os.environ.get("AFTERNOON_RUN_TIME", "21000")))
    configure_parser.add_argument("--window-end-buffer-seconds", type=int, default=int(os.environ.get("WINDOW_END_BUFFER_SECONDS", "900")))
    configure_parser.add_argument("--github-env", default=os.environ.get("GITHUB_ENV"))
    configure_parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    configure_parser.set_defaults(func=configure)

    clamp_parser = subparsers.add_parser("clamp")
    clamp_parser.add_argument("--step-label", required=True)
    clamp_parser.add_argument("--skip-env", required=True)
    clamp_parser.add_argument("--progress-buffer-seconds", type=int, default=1800)
    clamp_parser.add_argument("--window-end-buffer-seconds", type=int, default=int(os.environ.get("WINDOW_END_BUFFER_SECONDS", "900")))
    clamp_parser.add_argument("--github-env", default=os.environ.get("GITHUB_ENV"))
    clamp_parser.set_defaults(func=clamp)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
