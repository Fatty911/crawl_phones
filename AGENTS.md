# 全局规则

## 项目规则：工作流监控必须检查 Pages（最高优先级）

- **每次用户要求"监控工作流是否符合预期"时，必须同时检查：**
  1. 工作流运行日志（GitHub Actions logs）
  2. **Pages 页面实际内容**（`http://phones.jiucai.eu.org/data/latest.json`）
- **如果 Pages 内容不符合预期（如双源数据为0、行数不对），必须反推根因并定位问题**
- **禁止只看日志不看 Pages 就下结论**

## 配置修改必须验证（关键）

- **改任何软件配置后必须验证是否正确**，包括但不限于：OpenCode+OMO、Hermes-Agent、KiloCode、系统 cron、Git hooks 等
- **验证方法**：改完配置后立即执行相关命令确认无报错（如 `opencode --version`、`python3 -c "import json; json.load(open('config.json'))"`、`crontab -l` 等）
- **禁止**：改完配置直接同步推送而不验证，导致线上环境配置损坏
- **已有案例**：误删 `output` 字段导致 OpenCode 无法启动、cron 升级脚本 CRLF 换行符导致执行失败、plugin 字段重复导致 OMO 被禁用
- **已有案例**：`disabled_providers` 含不存在的 provider 名导致 OpenCode 计数错乱、本应禁用的 Provider 又显示出来

## 禁止操作（关键）

- **禁止添加用户未明确要求的新模型**：不自行判断"某个模型可能可用"就往 provider 白名单里加，必须等用户明确确认
- **禁止模型残留**：将某模型替换为同系列新版本时，必须从同一 provider 的白名单中**删除旧模型**。如 `glm-5.1 → glm-latest`、`qwen3.6-plus → qwen3.7-max`，不能新旧并存
- **禁止未联网查证**：修改模型配置前必须联网查询官方文档确认模型是否真实可用，严禁凭记忆或猜测添加模型
- **已有案例**：`kimi-k2.7-code` 未经验证加入 volcengine 白名单导致 Coding Plan 报不兼容、`glm-5.1` 和 `glm-latest` 共存违反替换规则

## Provider 白名单一致性校验（同步前强制）

- **每次改完 provider 配置后同步前**，必须运行以下校验确认无 ghost provider：
  ```python
  disabled = set(config["disabled_providers"])
  valid = set(config["provider"].keys())
  ghost = disabled - valid  # disabled 中有但 provider 中不存在的
  if ghost: 立即清理，禁止带着 ghost 同步
  ```
- **禁止**：`disabled_providers` 含不存在的 provider 名

## 网页 JS 无法渲染时的模型验证（关键）

- **优先使用 API 文档**：用 `context7_query-docs` 或 `webfetch` 查官方 API 参考（如 `https://api-docs.deepseek.com`）
- **搜索引擎找文本版**：用搜索引擎搜 `provider名 + supported models + coding plan` 找纯文本说明页面
- **实在找不到 → 必须问用户确认**：严禁自行添加未经验证的模型

## 模型配置原则

- **思考程度变体只保留最高思考程度**（如 DeepSeek 的 `reasoningEffort: max`，不保留 low/medium）
- **其它限制性越少越好**：能不配置 `input` 就不配（OpenCode 自动从 API 读取），`output` 如果 OpenCode 要求必须配则配
- **免费端点优先**：所有 fallback 链中，免费端点（NIM、OpenRouter free、Cloudflare、Modal、ModelScope）排在付费端点前面
- **弱模型不进评审链**：新增模型时，如果其在 Arena 或 Artificial Analysis 排行榜上排名低于当前已有模型列表中排名最低的模型，则不添加（排行榜随时间变化，不设固定门槛）

## Provider 优先级规则

所有 Agent 工具的 fallback 链都应遵循以下优先级顺序：

| 优先级 | 类型 | 示例 |
|---|---|---|
| 1 | 免费端点 | NVIDIA NIM、OpenRouter free、OpenCode Zen free、Cloudflare Workers AI、Modal、ModelScope |
| 2 | 单家 CodingPlan/TokenPlan | GLM CodingPlan、Kimi CodingPlan、MiMo TokenPlan |
| 3 | 聚合平台 CodingPlan/TokenPlan | 火山方舟、腾讯云、阿里云百炼、百度千帆 |
| 4 | 单家按量付费 | DeepSeek 官方、GLM 按量、Kimi 按量、MiMo 按量 |
| 5 | 聚合平台按量付费 | 火山方舟按量、阿里云按量 |

> ⚠️ **评审 Agent 内部也遵循此优先级**：每个 ReviewXXX 的 model 字段应放优先级最高的可用端点，fallback_models 按优先级递减排列。

## ⚠️ 【最高优先级】修改代码必须评审（不可跳过）

- **任何代码修改前必须调用多模型评审，无例外**
- **Git pre-commit hook 会硬阻断未评审的提交，没有后门**
- **禁止 `SKIP_REVIEW=1` 或 `ALLOW_UNREVIEWED_EDIT=1` 绕过评审**
- 评审流程：改代码 → `task(category="ReviewXXX")` 调用不同模型评审 → M≥2 通过 → `mark-review-passed` → commit
- **无论用户是否在当条消息中强调"禁止跳过评审"，都必须走评审流程**
- 主模型是 MiMo 则用 ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewQwen（排除 ReviewMimo）

## 文件编辑安全（关键）

- **修改文件时必须使用 `edit`（局部替换）。禁止使用 `write` 全量覆写，除非文件是全新的且不存在。**
- 编辑任何文件前，必须先用 `read` 工具读取该文件。禁止编辑未读取过的文件。
- 使用 `edit` 时，`oldString` 必须包含足够的上下文以唯一定位目标。禁止使用可能多次出现的单行匹配。
- 编辑后，必须通过回读修改区域或运行 `lsp_diagnostics` 验证文件完整性。
- 大文件（超过 300 行）应使用多次小的定向编辑，而非一次大的改动。
- **禁止截断或遗漏现有代码。** 如果不确定完整内容，再次读取文件后再编辑。

## 实时验证（关键）

- **写代码前必须联网搜索（web search、librarian、context7 等）验证事实、API、库用法和文档。禁止仅凭记忆或训练数据。**
- 使用任何库、框架或 API 时——即使是你"知道"的——必须先查阅最新文档。API 会变更、包会废弃、签名会演进。
- 对事实不确定时（版本号、方法签名、配置选项、废弃状态），将记忆视为过期数据，直到在线验证。
- 这尤其适用于：npm/pip/cargo 包、云服务商 API、框架版本、CLI 参数和配置格式。

## Provider 与模型配置（关键）

- **在 `opencode.json` 或 `oh-my-openagent.json` 中添加或更新任何 provider 时，必须：**
  1. **验证平台确实提供该模型**——搜索 provider 官方文档/公告。禁止假设所有 provider 遵循 OpenAI 兼容的模型命名规范，即使 base URL 以 `/v1` 结尾。
  2. **验证精确的模型 ID**——搜索 provider 的 API 文档获取正确的模型名称参数值。禁止猜测或从其他 provider 推断。
  3. **验证上下文窗口、最大输出和输入限制**——查阅官方规格。禁止编造这些数字。
  4. **检查模型变体（thinking/reasoning 级别）**——如果模型支持 `reasoning_effort` 或 `thinking` 变体（`low`/`medium`/`high`/`max`/`xhigh`），删除所有较低变体条目，在 models 列表和 whitelist 中只保留最高变体。禁止仅记录映射关系——必须从配置文件中物理删除较低变体。
  5. **提交前验证**——通过查阅 provider 当前的 API 文档确认模型 ID 确实可用，而非过期的缓存数据。
- **尚未支持某模型的平台不应配置该模型。** 移除或回退到平台支持的模型。
- **禁止为 provider 配置其未公开文档化的模型。**

## 修改范围纪律（关键）

- **只修改用户明确要求修改的内容。其他一律不动。**
- 禁止"改进"、"重构"、"清理"、"优化"或"修复"用户未提及的内容——无论问题看起来多明显。
- 禁止触碰相邻代码、附近函数、相关文件或导入，除非用户请求直接需要。
- 禁止添加注释、重新格式化、重命名变量或重组代码，除非明确要求。
- 如果发现范围外的真实问题，先提出警告。禁止悄悄修复。
- 不确定某修改是否在范围内时——不在范围内。先询问。

## 仓库目录整洁（关键）

- **新增或修改文件前，必须先判断文件应该放在哪个目录。** 代码、脚本、文档、测试、部署配置、临时产物应放到对应目录（如 `app/`、`scripts/`、`docs/`、`tests/`、`deploy/` 等），不得为了省事把新文件直接放在仓库根目录。
- 仓库根目录只允许放真正属于全项目级别的入口文件、核心配置、README/AGENTS、依赖清单等。调试脚本、一次性诊断文件、导出文件、日志、截图、图片、私密材料和构建产物不得放在根目录；用完即删，需保留则移动到合适目录并写明用途。

## GitHub Copilot 全局规则

- **Copilot 只保留免费模型**，不付费订阅 Copilot Pro/Pro+
- **白名单只保留 Arena + Artificial Analysis 综合排名靠前的 2 个免费模型**（2026-05 验证）：
  - `copilot.gpt-4.1`（Arena #95, AI Index 39）
  - `copilot.claude-haiku-4-5`（Arena #101, AI Index 37）
- **用途**：仅作为小 AGENT（sisyphus-junior）的 fallback 模型，不作为主模型或大 AGENT 模型
- **定期验证**：每季度检查 Arena 和 Artificial Analysis 排名，如有更优免费模型则替换

## 语言

- 所有回复使用中文。

## 模型准入门槛（关键）

给各 AGENT 工具（OpenCode+OMO、KiloCode、Hermes-Agent、OpenClaw、MiMo-Code 等）配置添加新模型时，**不得添加比已有模型列表中排行最低的模型排名更低的新模型**。

排行参考：
- https://artificialanalysis.ai/leaderboards/models?status=all
- https://arena.ai/leaderboard/text

操作流程：
1. 查看新模型在上述排行榜的排名
2. 确认当前配置中排名最低的模型
3. 如果新模型排名低于最低门槛，不添加

## 语法校验与测试（关键）

- **每次修改完代码后，必须进行严格的语法校验**（如运行 linter、类型检查、语法分析等），确保代码无语法错误、无类型错误、符合项目代码规范，不得提交或部署未通过语法校验的代码。
- **推送代码前，必须确保所有单元测试通过**。如果有测试框架，任何会导致测试失败的改动都不应推送。

## 多端体验一致性（关键）

- **所有设备的 OpenCode+OMO 使用体验应尽可能一致**：配置文件（opencode.json、oh-my-openagent.json、AGENTS.md、auth.json）在所有设备上保持同步
- **全局要求必须同步**：AGENTS.md 中的全局要求修改后，立即同步到所有设备家目录 + GitHub 仓库
- **仓库内配置必须对齐**：涉及 AI 调用的 git 仓库内如果有自己的 opencode.json/oh-my-openagent.json，必须与全局配置保持一致
- **同步全局配置后必须同步所有项目目录**：如果某个项目目录有独立的 opencode.json，同步全局时必须一并更新，避免出现 TUI 中已禁用的 Provider 又出现
- **同步全局 AGENTS.md 后必须同步所有项目目录**：`/root/crawl_cars`、`/root/.hermes` 等项目目录如果有自己的 AGENTS.md，用全局最新版本覆盖。同理 E:\Codes 下的所有 repo 也要同步

## 提交推送与运行监测（关键）

- **任务完成后必须自动提交并推送**：在确保代码质量、语法校验和必要测试通过后，必须自动 `commit` 并 `push`，不能只把改动留在本地。若项目要求 Pull Request，推送后创建或更新 PR，并在 CI 通过后继续合并；除非用户明确要求暂停或只做本地改动。
- **推送、热更新、重启或部署容器后必须监测运行情况**：必须继续检查 CI/容器状态、健康接口和关键日志，确认服务持续运行后再交付结论。
- **推送代码前，必须确保所有单元测试通过**：如果有测试框架，任何会导致测试失败的改动都不应推送。
- **推送后必须监控 CI 测试**：提交推送完必须至少监控到测试成功；如果时间窗口允许修改的工作流运行，还应监控修改的工作流运行结果是否符合预期。

## 多模型共识评审机制（关键）

> ⚠️ **【强制规则】所有代码修改前必须触发多模型共识评审，无例外。**
> 
> 这是解决"不同模型改出来的代码各不一样、花式报错"问题的核心机制。

### 核心原则

- **任何代码修改都必经共识评审**（除纯查询/读取操作外）
- **通过并行启动多个 Oracle 子任务实现多模型评审**——Oracle 是只读 agent，天然适合评审
- **N 选 M 通过制**：并行启动 N 个 Oracle，设通过阈值 M（如 N=3，M=2 即至少 2 个通过就放行）。部分模型因限额/网络不可用时不影响整体
- **流程**：用户发起修改 → Sisyphus 并行启动 N 个 Oracle 评审 → 收集结果 → 按 M 阈值判断是否通过
- Oracle **只有读权限**（不可 edit/bash），不会修改代码

### ⚠️ 技术限制：为什么不能用自定义 Review Agent

`task()` 的 `subagent_type` 参数是**固定枚举**（oracle, explore, librarian, metis, momus 等），不支持自定义 agent 名称。在 `oh-my-openagent.json` 中定义的 ReviewGLM/ReviewDeepseek 等自定义 agent **无法通过 `task(subagent_type="ReviewGLM")` 调用**，OMO 插件不会路由到自定义名称。因此评审必须使用 `task(subagent_type="oracle")` 实现。

### 共识评审工作流程

```
主控 agent（sisyphus）收到修改请求
  │
  ├── 第一步：确定当前主模型，排除对应的 Review category
  │   例如主模型是 volcengine-coding/glm-5.1 → 排除 ReviewGLM
  │   从剩余 Review category 中选 3 个并行启动
  │
  ├── 第二步：Sisyphus 启动前 3 个评审任务
  │   task(category="ReviewDeepseek", prompt="...", run_in_background=true)
  │   task(category="ReviewKimi", prompt="...", run_in_background=true)
  │   task(category="ReviewMimo", prompt="...", run_in_background=true)
  │
  ├── 第三步：监控评审状态（每 3 分钟检查一次）
  │   - 如果 3 个全部通过 → 立即继续任务
  │   - 如果 3 个中达到 M=2 通过 → 立即继续任务
  │   - 如果 3 个中通过不足 M 个 → 启动第 4 个（ReviewQwen 等）
  │   - 逐个启动后续 Review，直到达到 M 个通过或全部用完
  │   - 主 Agent 每 3 分钟检查一次未返回结果的评审状态
  │
  ├── 第四步：收集评审结果
  │   - 后续返回的评审结果如果提出问题 → 主 AGENT 必须查看并改进
  │   - 后续返回的评审结果没提出问题 → 忽略，提升效率
  │
  └── 第五步：标记评审通过 → 同步到全端 → 推送
```

### 评审 Category 模型覆盖

每个 review category 绑定独立模型，确保多模型交叉验证：

| Category | 主模型 | Fallback | 定位 |
|---|---|---|---|
| **ReviewGLM** | volcengine-coding/glm-5.1 | nvidia-glm-5.1, modal-glm-5.1, modelscope-glm-5 | GLM-5.1 评审 |
| **ReviewDeepseek** | deepseek/deepseek-v4-pro | volcengine-deepseek | DeepSeek V4 评审 |
| **ReviewKimi** | volcengine-coding/kimi-k2.6 | nvidia-kimi, cloudflare-kimi, openrouter-kimi-free, cf-kimi-k2.7 | Kimi K2.6 评审 |
| **ReviewQwen** | alibaba/qwen3.7-max | — | Qwen 3.7 评审 |
| **ReviewMimo** | mimo-tokenplan/mimo-v2.5-pro | — | MiMo V2.5 评审 |
| **ReviewMinimax** | nvidia/nvidia-minimax-m3 | — | MiniMax M3 评审 |
| **ReviewGrok** | proxy_xai/grok-4.3 | — | Grok 4.3 兜底评审 |

> ⚠️ **设计原则**：每个 ReviewXXX 只包含 XXX 家的模型。优先调用 ReviewGLM/ReviewKimi/ReviewDeepseek，ReviewGrok 作为兜底。

### 评审 Provider 优先级（每个 ReviewXXX 内部）

| 优先级 | 类型 | 示例 |
|---|---|---|
| 1 | 免费端点 | nvidia, OpenCode Zen, OpenRouter free, Cloudflare, Modal, ModelScope |
| 2 | 单家 Plan | GLM CodingPlan, Kimi CodingPlan, MiMo TokenPlan |
| 3 | 聚合平台 Plan | 火山方舟, 腾讯云, 阿里云百炼, 百度千帆 |
| 4 | 单家按量付费 | DeepSeek 官方, GLM 按量, Kimi 按量, MiMo 按量 |
| 5 | 聚合平台按量付费 | 火山方舟按量, 阿里云按量 |

### 评审模型选择规则（强制）

**评审必须使用和写代码的主模型不同的模型，禁止用同模型评审自己的代码。**

选择逻辑：
1. 当前主模型是哪家 → 排除对应的 Review category
2. 从剩余 Review category 中选 3 个并行评审
3. 都不可用时，用 ReviewGrok 兜底

| 主模型 | 排除 | 评审优先选择 |
|---|---|---|
| DeepSeek V4 Pro | ReviewDeepseek | ReviewGLM + ReviewKimi + ReviewQwen + ReviewMimo + ReviewMinimax |
| GLM-5.1 | ReviewGLM | ReviewDeepseek + ReviewKimi + ReviewQwen + ReviewMimo + ReviewMinimax |
| Kimi K2.6 | ReviewKimi | ReviewGLM + ReviewDeepseek + ReviewQwen + ReviewMimo + ReviewMinimax |
| Qwen 3.7 Max | ReviewQwen | ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewMimo + ReviewMinimax |
| MiMo V2.5 Pro | ReviewMimo | ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewQwen + ReviewMinimax |
| MiniMax M3 | ReviewMinimax | ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewQwen + ReviewMimo |
| 其它模型 | 无 | ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewQwen + ReviewMimo + ReviewMinimax |

> 任何 Review 不可用时，用 ReviewGrok（proxy_xai/grok-4.3）兜底补审。

**禁止跳过评审直接修改代码。**

### 默认评审策略

> **用户未明确指定评审参数时，自动采用以下默认策略：**
> - **N=3**（并行启动 3 个 Oracle）
> - **M=2**（3 中至少 2 票通过即放行）
> - 无需再次询问用户，直接并行启动评审
>
> ⚠️ **服务器资源限制**：当前生产服务器为 2核4G，3 个 Oracle 并行评审峰值额外内存消耗约 90-240MB。

### 评审结果模型标注（强制）

- **评审 Oracle 必须在结果第一行注明所使用的模型名称**，格式：`模型：xxx`
- prompt 中加入：`请在评审结果第一行注明你所使用的模型名称（格式："模型：xxx"）。`
- 如果模型无法确定自身名称，则注明 fallback 链中该序号对应的预期模型
- **评审结果不得匿名，必须可追溯到具体模型**
- 汇总评审结果时，必须展示每个评审对应的模型名称

### Git Pre-commit Hook 强制评审（底层强制）

> **除了提示词层面的规则，Git 层面也强制要求评审：**

**Hook 位置**: `C:\Users\Administrator\.git-hooks\pre-commit`

**工作机制**：
1. 每次 `git commit` 前，hook 检查是否有代码修改（排除 `.md`/`.txt`/`.json` 纯文档）
2. 如果有代码修改，要求先通过多模型评审
3. 评审通过后，调用 `~/.git-hooks/mark-review-passed` 创建临时标记文件（有效期 5 分钟）
4. 标记文件存在时，允许提交

**跳过方式**（仅紧急情况）：
```bash
SKIP_REVIEW=1 git commit -m "emergency fix"
```

**评审通过后必须执行**：
```bash
~/.git-hooks/mark-review-passed review-glm.txt review-kimi.txt review-deepseek.txt
```

> ⚠️ **marker 脚本必须接收评审任务的实际输出文件**，不能让模型自己编摘要。pre-commit hook 会验证标记文件包含真实评审内容，否则拒绝提交。

> ⚠️ **这是底层强制机制，即使模型忘记提示词规则，Git 也会阻止未评审的代码提交。**

**适用范围**：
- **Windows (E:\Codes\)**: AI_XR_Relay_familyai, aider, Auto_add_notes_to_WeChat_group_members, AutoBuild_OpenWrt_for_XiaoMi_R4, Badminton-court-management-system, billiards_tqt, crawl_cars, LibreChat, lobe-chat, opencode-stock, Personal_commonly_used, tabby, zbpack_tmp
- **Windows (C:\Users\)**: Personal_commonly_used, hermes-agent
- **racknerd**: hermes-agent, AutoBuild_OpenWrt, crawl_cars, LibreChat, lobe-chat, Badminton-court, opencode-stock, /root 主 repo
- **jstq**: AutoBuild_OpenWrt, billiards_tqt
- **dmit**: 无 repo，仅安装 mark-review-passed 到 PATH

### Git Pre-push Hook 强制单元测试（底层强制）

> **除了评审，Git 层面也强制要求单元测试通过：**

**Hook 位置**: `C:\Users\Administrator\.git-hooks\pre-push`

**工作机制**：
1. 每次 `git push` 前，hook 检测项目类型（Node.js/Python/Go/Java）
2. 自动运行对应的完整测试套件（`npm test` / `pytest` / `go test` / `mvn test` / `gradlew test`）
3. 测试全部通过才允许推送
4. 测试失败则拒绝推送

**支持的项目类型**：
- **Node.js**: `npm test`（检测 `package.json` 中的 test 脚本）
- **Python**: `pytest`（检测 `pytest.ini` / `pyproject.toml` / `setup.py`）
- **Go**: `go test ./...`（检测 `go.mod`）
- **Java Maven**: `mvn test`（检测 `pom.xml`）
- **Java Gradle**: `./gradlew test`（检测 `build.gradle`）

**跳过方式**（仅紧急情况）：
```bash
SKIP_TESTS=1 git push
```

### Git Hooks 文件清单

| Hook | 触发时机 | 检查内容 | 跳过方式 |
|------|----------|----------|----------|
| **pre-commit** | `git commit` | 多模型评审 + 快速测试 | `SKIP_REVIEW=1` |
| **pre-push** | `git push` | 完整单元测试 | `SKIP_TESTS=1` |

> ⚠️ **这是底层强制机制，即使模型忘记提示词规则，Git 也会阻止未评审、未测试的代码提交和推送。**

## 代码级限制（程序强制）

> 以下限制尽量使用 Git hooks 和 OMO 运行包补丁实现，不能把普通提示词当成硬约束。

### 当前真实生效的硬防线

| 防线 | 位置 | 强制内容 |
|------|------|---------|
| **OMO edit/write/multiedit 评审拦截** | `C:\Users\Administrator\node_modules\oh-my-openagent\dist\index.js` 本地补丁 | 代码文件修改前必须存在 10 分钟内的 `/tmp/.review_passed_*` 标记；`.md/.txt/.json` 豁免 |
| **runtime_fallback 静默成功检测** | `oh-my-openagent` 本地补丁 + `oh-my-openagent.json` | DeepSeek 类 provider 如果 `finish=stop` 但无可见输出/0 output token，则转成 retryable failure 进入 fallback |
| **pre-commit** | `C:\Users\Administrator\.git-hooks\pre-commit` | 代码提交前必须存在 5 分钟内的评审标记 |
| **pre-push** | `C:\Users\Administrator\.git-hooks\pre-push` | 推送前运行项目测试 |

### 评审强制机制（edit/write 前硬阻断）

代码文件修改前必须先完成多模型评审，并执行：

```bash
~/.git-hooks/mark-review-passed
```

当前本机 OMO 运行包已补丁化：`write` / `edit` / `multiedit` 修改代码文件时，如果 10 分钟内没有 `.review_passed_*` 标记，工具调用会直接失败。此限制用于防止 MiMo 等模型忘记或忽略 AGENTS.md。

**重要限制**：这是本机 npm 包补丁，不是上游 OMO 官方能力。升级或重装 `oh-my-openagent` 后必须重新检查/重打补丁；否则 edit 层硬阻断会退化为只有 Git pre-commit 阻断。

### DeepSeek 静默截断处理

DeepSeek 官方 API 便宜，继续使用；但如果它返回 `finish=stop` 且无可见输出或 output token 为 0，不得视为成功。当前 `runtime_fallback.silent_success_detection` 已启用，命中后会构造 `SilentCompletionError`，让 OMO fallback/retry 接管。

### 辅助脚本

| 脚本 | 位置 | 用途 |
|------|------|------|
| **pre-edit-guard.sh** | `~/.config/opencode/hooks/` | 外部脚本版编辑检查；仅在被显式调用时生效，不能假设 OMO 官方会自动执行 |
| **config-sync-validator.sh** | `~/.config/opencode/hooks/` | opencode.json/kilo.json/omo.json 配置同步校验 |
| **validate-model-whitelist.sh** | `~/.config/opencode/hooks/` | Provider whitelist 与 models 定义一致性校验 |
| **pre-save-validator.sh** | `~/.config/opencode/hooks/` | JSON/YAML/Python 保存前语法自动校验 |
| **post-edit-diagnostics.sh** | `~/.config/opencode/hooks/` | 编辑后运行 LSP 诊断（TS/JS/Python/Go/Shell） |
| **code-pattern-guard.py** | `~/.config/opencode/hooks/` | 禁止 `as any`、`@ts-ignore`、`@ts-expect-error`、空 catch 块、console.log 残留 |

### Git Hooks 集成

所有上述代码级检查已集成到 Git pre-commit hook 中：

```
pre-commit hook 检查流程:
  1. 多模型评审检查（必须）
  2. 代码模式校验 (code-pattern-guard.py)（警告，不阻断）
  3. 配置同步校验 (config-sync-validator.sh)
  4. 模型白名单校验 (validate-model-whitelist.sh)
  5. 快速测试检查
```

跳过方式：
- `SKIP_REVIEW=1 git commit` — 跳过所有检查
- `SKIP_CONFIG_SYNC=1 git commit` — 仅跳过配置同步检查蛎

## 总结

- edit > write（已有文件，始终如此）🔒 程序级强制
- 先读后改（无例外）🔒 程序级强制
- 改后验证（始终如此）🔒 程序级强制
- 写代码前联网验证（禁止凭记忆）
- 只改用户让改的（禁止擅自修改）
- 回复使用中文（始终如此）
- 语法校验后才可提交（始终如此）🔒 程序级强制
- 测试通过后才可推送（始终如此）🔒 程序级强制
- 代码修改前必须多模型共识评审（无例外）🔒 程序级强制
- 禁止 `as any` / `@ts-ignore` / 空 catch 🔒 程序级强制
- Provider 模型配置一致性 🔒 程序级强制
- 配置跨文件同步 🔒 程序级强制
- Git pre-commit hook 底层强制评审（无法跳过）
- Git pre-push hook 底层强制单元测试（无法跳过）

## 配置同步（关键）

只要涉及到配置模型，以下所有位置必须同步改写，无一例外：

> ⚠️ **盘符规则**：Windows10 和 Windows11 双系统，各自启动后自己的系统盘都是 C:，另一个系统盘都是 D:。同步时始终用 C: → D:（当前系统推送到另一系统），无需关心当前是哪个系统。
>
> ⚠️ **使用习惯**：用户习惯右键点击开始菜单运行终端，终端默认运行在用户家目录（`C:\Users\Administrator`）。因此用户可能在任意一个 Windows 系统的 Administrator 目录下运行 OpenCode、配置 OpenCode+OMO。配置文件实际位置取决于当前启动的系统盘符。

1. **本机 opencode 配置**: `C:\Users\Administrator\.config\opencode\opencode.json`
2. **本机 OMO 插件配置**: `C:\Users\Administrator\.config\opencode\oh-my-openagent.json`
3. **本机 auth 配置**: `C:\Users\Administrator\.local\share\opencode\auth.json`
4. **另一系统 opencode 配置**: `D:\Users\Administrator\.config\opencode\opencode.json`
5. **另一系统 OMO 插件配置**: `D:\Users\Administrator\.config\opencode\oh-my-openagent.json`
6. **另一系统 auth 配置**: `D:\Users\Administrator\.local\share\opencode\auth.json`
7. **本机 KiloCode 配置**: `C:\Users\Administrator\AppData\Roaming\kilo\kilo.json`
8. **GitHub 所有涉及 AI 调用的仓库**:
   - `Fatty911/Personal_commonly_used/ai_tools/opencode/`
   - `Fatty911/Personal_commonly_used/ai_tools/KiloCode/`
   - `Fatty911/hermes-agent`
9. **远程服务器 root@racknerd.jiucai.eu.org**:
   - `/root/.config/opencode/opencode.json`
   - `/root/.config/opencode/oh-my-openagent.json`
   - `/root/.local/share/opencode/auth.json`
   - `/root/.hermes/config.yaml`
   - `/root/.hermes/auth.json`
10. **远程服务器 root@jstq.com.cn**:
    - `/root/.config/opencode/opencode.json`
    - `/root/.config/opencode/oh-my-openagent.json`
    - `/root/.local/share/opencode/auth.json`
11. **远程服务器 root@dmit.jiucai.eu.org**:
    - `/root/.config/opencode/opencode.json`
    - `/root/.config/opencode/oh-my-openagent.json`
    - `/root/.local/share/opencode/auth.json`

改写时统一遵循以下原则：
- 只保留最新代模型（如 DeepSeek V4、Kimi K2.6、GLM-5.1、Qwen 3.7）
- 变体只保留最高思考程度
- 免费优先，付费辅助
- 各 Provider 按用户指定规则精简白名单

## ⚠️ plugin 字段跨端差异（关键）

- **Windows**：需要 `plugin: ["oh-my-openagent@latest"]` 手动声明（npm 自动检测不生效）
- **Linux**（racknerd/jstq/dmit）：npm 自动检测 + 手动声明**都用 `oh-my-openagent@latest`** 格式，两者一致不会重复
- **同步后无需特殊处理**：`oh-my-openagent@latest` 在 Windows 和 Linux 端通用，不再需要同步后清空 plugin 字段
- **禁止**：使用 `oh-my-openagent`（不带 `@latest`），会导致 Linux 端 OMO 重复注入被禁用

## 已知 Bug 与解决方案

### 自动升级脚本分离

OpenCode 和 Hermes-Agent 的自动升级脚本分开管理，互不影响：

| 脚本 | 位置 | 升级内容 | cron |
|---|---|---|---|
| **auto-upgrade-all.sh** | `/root/.config/opencode/scripts/` | OpenCode + OMO 插件 | `0 0,10,20 * * *` |
| **auto-upgrade-hermes.sh** | `/root/.hermes/` | Hermes-Agent + Gateway | `0 0,10,20 * * *` |

- 删除 Hermes-Agent 不会影响 OpenCode 升级
- 日志分别存储在各自目录下
- 脚本已同步到 racknerd 和 jstq

### 1. OMO 重复注入被禁用
- **现象**：OpenCode 启动时显示 "Duplicate OMO plugin entries detected"，TUI 只显示 Build 和 Plan
- **根因**：`plugin: ["oh-my-openagent"]` 与 npm 自动检测的 `oh-my-openagent@latest` 字符串不同，被当成两个实例
- **解决**：统一使用 `plugin: ["oh-my-openagent@latest"]`，与 npm 检测结果一致
- **已修复**：2026-06-13

### 2. npm 升级 OMO 失败 (ENOTEMPTY)
- **现象**：自动升级脚本执行 `npm install -g oh-my-openagent@latest` 报 `ENOTEMPTY: directory not empty, rename`
- **根因**：npm 升级时旧目录残留 `.oh-my-openagent-*` 临时目录，阻止重命名
- **解决**：在 npm install 前加 `rm -rf /usr/lib/node_modules/.oh-my-openagent-*`
- **已修复**：2026-06-12（racknerd + jstq 升级脚本已更新）

### 3. OpenCode 版本过旧导致 OMO 不识别
- **现象**：racknerd 上 OpenCode 1.14.41，OMO Agent 不显示
- **根因**：自动升级脚本用 `curl https://opencode.ai/install.sh`（URL 多了 `.sh`），404 静默失败
- **解决**：修正为 `curl https://opencode.ai/install`，并加 npm 三重保险
- **已修复**：2026-06-02

### 4. OMO 自定义 category 不生效
- **现象**：`task(category="ReviewGLM")` 报 "Unknown category"
- **根因**：OMO 在 session 启动时缓存 category 列表，session 内修改配置不生效；且旧版本可能不支持自定义 category
- **解决**：改完 OMO 配置后必须重启 OpenCode session；使用 `@latest` 格式确保版本最新
- **已修复**：2026-06-12

### 5. 自定义 subagent_type 不可用
- **现象**：`task(subagent_type="ReviewGLM")` 报错，无法调用自定义 Agent
- **根因**：`task()` 的 `subagent_type` 是固定枚举（oracle, explore, librarian 等），不支持自定义名称
- **解决**：改用 `task(category="quick/deep/ultrabrain")` 实现多模型评审分发
- **已修复**：2026-06-12

### 6. OpenCode SessionRetry 无限重试
- **现象**：provider 月限额后 fallback 不切换，同一模型重试 10+ 次
- **根因**：OpenCode 内部 SessionRetry 对 5xx/403 无限重试（指数退避），OMO fallback 永远等不到介入机会
- **解决**：手动切换主模型；等 OpenCode 官方合并 maxAttempts 配置（GitHub issue #26675）
- **状态**：未解决，OpenCode 已知缺陷
// test review config - 06/02/2026 19:08:15
