#!/bin/bash
# 定时监控工作流和 Pages 数据
# 工作流预估完成时间：
#   - 有 .done marker: 即时（1秒）
#   - 无 .done marker + 增量扫描: ~2-3小时
#   - 合并分析: ~1分钟
#   - Pages 部署: ~1分钟
# 爬虫触发时间: 00:30 / 05:30 UTC
# 安全检查时间: 08:00 / 14:00 UTC（覆盖最坏情况 05:30 + 3h）

set -e
cd /root/crawl_phones

LOG_FILE="/root/crawl_phones/scripts/monitor_$(date +%Y%m%d_%H%M).log"
echo "=== 工作流监控 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG_FILE"

opencode run "$(cat /root/crawl_phones/scripts/monitor_prompt.md)" 2>&1 | tee -a "$LOG_FILE"
