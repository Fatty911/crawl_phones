# 全局规则（所有 AI Agent 必须遵守）

## 语言
- 所有回复使用中文。

## 执行风格（强制遵守）
- **一次性完成全部任务**：用户提出的需求，必须一次性全部完成，不得询问"是否分步完成"、"先做哪些"等问题。
- **不等待确认**：除非存在明确的歧义或多种解读可能导致截然不同的结果，否则直接执行，不问"可以吗"、"是否继续"。
- **全面覆盖**：每次任务必须覆盖用户已提出的**所有**需求，遗漏任何一项即为失败。
- **禁止拖延**：不要说"我建议先...然后再..."，直接并行处理所有任务。

## 指令分类
- 收到用户指令时，必须判断这是**单次任务**（解决具体报错、一次性操作）还是**全局提示**（应贯穿所有会话始终遵守的规则）。
- 如果是全局提示，必须立即修改或追加到本文件（`AGENTS.md`）中，确保上下文压缩后仍可恢复。

## 代码修改与提交
- 调试过程中产生的临时文件（如 `*.py`、`*.sh`、`*.log`等），验证完成后如无后续用途则删除，不要留一堆临时文件。
- 本地 commit 可以随时做；完成代码、工作流或文档改动并提交后，默认自动 push 到远端，不再询问用户是否推送。
- 单次解决报错的改动可自动 push，多次循环尝试时注意 push 间隔时间。
- **每次修改完代码后，必须进行严格的语法校验**（如运行 linter、类型检查、语法分析等），确保代码无语法错误、无类型错误、符合项目代码规范，不得提交或部署未通过语法校验的代码。

## 文档同步
- 每次执行完任务后，必须检查 README.md 和 AGENTS.md 是否需要更新（新增/删除/重命名了文件、功能、配置项，或新增了全局规则等）。
- **每次更新完代码后，必须自动更新对应文档**：
  - 修改了爬虫脚本 → 更新 README.md 中的文件详解、命令行参数、步骤说明
  - 修改了工作流 → 更新 README.md 中的工作流调度、触发条件、Job 结构
  - 修改了过滤条件 → 更新 README.md 和 CRAWL_SCOPE.md
  - 修改了代理相关 → 更新 README.md 和 DOCKER_DEPLOY.md 中的代理配置说明
  - 修改了部署脚本 → 更新 VPS_DEPLOY.md 或 DOCKER_DEPLOY.md
  - 新增/删除了文件 → 更新 README.md 的目录结构
  - 任何代码变更 → 更新 CHANGELOG.md 和 HISTORY.md
- 每次对话结束时，必须更新 HISTORY.md（融合进现有总结，不是新建文件）。

## 爬虫时间窗口与外部触发
- 手机和汽车配置爬虫统一只在北京时间 `08:00-12:30`、`13:00-22:00` 两个窗口执行长爬取步骤。
- 不依赖 GitHub Actions `schedule` 保证准点触发；外部触发优先使用 cron-job.org API，时间固定在北京时间约 `08:30` 和 `13:30`。
- 无论任何入口启动，workflow 必须自动判断“当前窗口剩余时间”和“GitHub Actions 6 小时限制剩余时间”，按更早的截止点提前预留提交进度时间并结束。
- 改动工作流时必须保留 `custom_scripts/crawl_budget.py` / `custom_scripts/configure_cron_job_org.py` 这类护栏，避免重新退回只靠 cron schedule 的方案。

## 模型与 API 选择
- 优先选择排行榜前 25 且有免费资源的模型。
- 当前已知免费渠道：
  - **AtomGit**：`zai-org/GLM-5`、`Qwen/Qwen3.5-397B-A17B`（无限量，500次/分，端点 `https://api-ai.gitcode.com/v1`）
  - **Modal**：GLM-5.1-FP8 并发1不限量
  - **ModelScope**：每日限量
  - **NVIDIA NIM**：`nemotron-3-super`（免费，端点 `https://integrate.api.nvidia.com/v1`）
  - **ZEN**：排行榜前 25 的免费模型
  - ~~智谱官方 GLM-4-Flash~~：老旧模型性能差，不再使用
- OpenRouter 的 mimo-v2-pro 和 qwen3.6-plus 已不再免费，不要使用。
- 当日志过长导致超出当前模型上下文时，必须清晰打印提示信息并优雅降级到下一个模型/提供商。

## auto_fix_workflow.py 配置
- 支持 `XXXX_API_KEY`、`XXXX_MODEL_LIST`、`XXXX_PROXY_URL` 格式的环境变量（参考 Lobe-Chat 风格）。
- `XXXX_API_KEY` 存在 → 启用该 Provider。
- `XXXX_MODEL_LIST` **非必填**：
  - 未配置 → 只使用排行榜前10且 context >=1M 的模型。
  - 已配置 → 使用排行榜前10(1M+) 与 MODEL_LIST 的**并集**。
- `XXXX_PROXY_URL` **非必填**。
- 如果未读取到 `XXXX_MODEL_LIST` 变量，运行工作流时**不要报错**，直接使用排行榜模型。

## 当前已配置的 Provider（GitHub Secrets）
- ACTION_PAT
- ATOMGIT_API_KEY
- MINIMAX_API_KEY
- MINIMAX_CODING_PLAN_API_KEY
- MODAL_API_KEY
- MODELSCOPE_API_KEY
- MOONSHOT_API_KEY
- NVIDIA_NIM_API_KEY
- OPENROUTER_API_KEY
- PROXY_SUBSCRIPTIONS
- XAI_API_KEY
- ZEN_API_KEY

## opencode 配置
- opencode.json 必须使用合法 schema：`provider`（单数）和 `agent`（单数），不能用复数形式。
- oh-my-openagent 的多 agent 协同效果更好，优先使用。

## 旧模型必须隐藏
- TUI 中不得显示已过时的旧版模型（如 qwen-long、qwen2.5 系列等），通过自定义 provider + whitelist 控制显示的模型。
- OpenCode 不支持 disabled_providers 字段，正确做法：为每个自定义 provider 设置 whitelist，只列出需要显示的模型。
- 内置 provider（alibaba、alibaba-cn、minimax 等）自带大量旧模型，可通过自定义同名 provider + whitelist 覆盖，或直接不使用这些 provider。
- 让 TUI /models 显示的列表中，隐藏掉旧的和性能弱的模型：
  - 无论哪家提供 Claude 模型都不要显示 Haiku 系列。
  - Opus 和 Sonnet 最新的是 4.6 代，不要显示 4.5 及前代模型。
  - GPT 系列不要显示后缀带 mini、low、medium 的弱模型，可以不带后缀，可以后缀为 high 或 codex。
- 免费模型只显示最新最强的三两个。
