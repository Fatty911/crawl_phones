监控 GitHub Actions 工作流运行情况和 Pages 页面数据是否符合预期。

## 检查清单
1. 查看最近 5 个 GitHub Actions 运行状态
2. 查看 http://phones.jiucai.eu.org/data/latest.json 的双源数据量
3. 检查中关村在线和太平洋电脑网两个爬虫工作流是否有报错
4. 检查合并分析工作流是否正常运行
5. 检查 Pages 是否部署成功

## 如果发现问题
- 调取报错工作流的日志，定位根因
- 如果双源显示为 0，GOTO auto_fix_rules

## auto_fix_rules
如果 pages 双源数据显示为 0 或不符合预期，参照以下步骤：
1. 反推根因（检查工作流日志、artifact、Pages 数据）
2. 自动修复（修改代码 → 多模型评审 → 提交推送）
3. 等待修复生效后再确认
