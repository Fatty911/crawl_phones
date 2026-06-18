#!/bin/bash
# 定时监控工作流和 Pages 数据（调试期最多运行 7 天，之后自动停止）
set -e
cd /root/crawl_phones

COUNTER_FILE="/root/crawl_phones/scripts/.monitor_count"
MAX_RUNS=14
RUN_COUNT=1

if [ -f "$COUNTER_FILE" ]; then
  RUN_COUNT=$(($(cat "$COUNTER_FILE") + 1))
fi

if [ "$RUN_COUNT" -gt "$MAX_RUNS" ]; then
  # 超过限制，自动移除 cron 并退出
  crontab -l 2>/dev/null | grep -v "monitor_run" | crontab -
  echo "$(date '+%Y-%m-%d %H:%M:%S') 已运行 ${RUN_COUNT} 次（超过 ${MAX_RUNS} 次上限），自动停止" >> /root/crawl_phones/scripts/monitor.log
  exit 0
fi

echo "$RUN_COUNT" > "$COUNTER_FILE"

LOG_FILE="/root/crawl_phones/scripts/monitor_$(date +%Y%m%d_%H%M).log"
echo "=== 工作流监控 #$RUN_COUNT/$MAX_RUNS $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG_FILE"

opencode run "$(cat /root/crawl_phones/scripts/monitor_prompt.md)" 2>&1 | tee -a "$LOG_FILE"
