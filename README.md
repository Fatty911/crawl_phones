# 手机配置数据爬虫项目

自动爬取中关村在线和太平洋电脑网的手机配置数据，通过AI搜索获取BL锁和Root信息，并生成数据文件供Release使用。

## 项目概述

本项目模仿汽车爬虫架构，实现：
- **双数据源爬取**：中关村在线 + 太平洋电脑网，数据互相验证
- **AI智能搜索**：自动搜索每款手机的BL锁解锁和Root情况
- **GitHub Pages展示**：高级筛选、筛选历史、排序、导出的网页表格
- **自动化工作流**：定时爬取、合并、发布

## 目录结构

```
crawl_phones/
├── crawl_zol.py              # 中关村在线爬虫脚本
├── crawl_pconline.py         # 太平洋电脑网爬虫脚本
├── merge_phones.py           # 数据合并脚本
├── search_root_info.py       # AI搜索BL锁和Root信息
├── requirements.txt          # Python依赖
├── README.md                 # 项目说明
├── CHANGELOG.md              # 变更记录
├── HISTORY.md                # 修复与运维历史
├── docs/phones/              # GitHub Pages前端
│   ├── index.html            # 页面结构
│   ├── styles.css            # 样式
│   └── app.js                # 数据加载、高级筛选、筛选历史、排序、分页、导出逻辑
├── custom_scripts/           # GitHub Actions 辅助脚本
│   ├── configure_cron_job_org.py # 配置 cron-job.org 外部触发
│   ├── crawl_budget.py       # 计算北京时间窗口和 Actions 6 小时预算
│   ├── git_sync_progress.sh  # 进度提交的 rebase/push 重试
│   ├── merge_progress_json.py # 进度文件冲突合并
│   ├── validate_syntax.py    # 本地和 CI 语法校验
│   └── validate_workflow_expectations.py # workflow 护栏校验
├── zol/                      # 中关村在线数据目录
│   ├── json/                 # 单个手机JSON文件
│   ├── exception/            # 异常记录
│   └── progress.json         # 进度文件
├── pconline/                 # 太平洋电脑网数据目录
│   ├── json/                 # 单个手机JSON文件
│   ├── exception/            # 异常记录
│   └── progress.json         # 进度文件
├── ai_search/                # AI搜索数据目录
│   └── progress.json         # 搜索进度文件
└── .github/workflows/
    ├── ci.yml                # Python/workflow 静态校验
    ├── crawl-zol.yml         # 中关村在线爬虫工作流
    ├── crawl-pconline.yml    # 太平洋电脑网爬虫工作流
    ├── crawl-trigger.yml     # cron-job.org 入口触发器
    ├── deploy-pages.yml      # 静态网页独立发布工作流
    └── merge-and-deploy.yml  # 合并、AI搜索、发布工作流
```

## 核心功能

### 1. 双数据源爬取

**中关村在线 (ZOL)**
- 列表页: `https://detail.zol.com.cn/cell_phone_index/subcate57_list_{page}.html`
- 详情页: `https://detail.zol.com.cn/cell_phone/index{phone_id}.shtml`
- 参数页: `https://detail.zol.com.cn/{category_id}/{phone_id}/param.shtml`
- 字符编码: GBK
- 每页手机数: ~146个
- 推荐请求间隔: 2-3秒

**太平洋电脑网 (PConline)**
- 品牌目录: `https://product.pconline.com.cn/mobile/`
- 列表页: `https://product.pconline.com.cn/mobile/{brand}/` (第1页)
- 列表页分页: `https://product.pconline.com.cn/mobile/{brand}/{n}s1.shtml` (n = (page-1) * 25)
- 详情页: `https://product.pconline.com.cn/mobile/{brand}/{phone_id}.html`
- 参数页: `https://product.pconline.com.cn/mobile/{brand}/{phone_id}_detail.html`
- 字符编码: GBK (GB2312)
- 推荐请求间隔: 3-5秒

### 2. AI搜索BL锁和Root信息

`search_root_info.py` 会在增量爬虫完成后运行，为每款手机搜索：
- **是否可解BL锁**: 是/否/免解锁/未知
- **是否可root**: 是/否/未知
- **解锁方式**: 官方申请/工程线/漏洞利用/未知
- **root方案**: Magisk/KernelSU/SuperSU/未知
- **风险等级**: 低/中/高/未知
- **信息来源**: XDA/酷安/官方文档/GitHub/未知

### 3. 数据合并与验证

`merge_phones.py` 合并两个数据源：
- 统一字段名映射
- 数据规范化处理
- 同名机型合并为单条记录，标记 `单源` / `双源一致` / `双源差异`
- 差异对比（同一手机不同来源的配置差异）
- 输出合并CSV/JSON

### 4. GitHub Pages展示

前端功能：
- 全局搜索：品牌、型号、配置项
- 快速筛选：品牌、是否可Root、是否可解BL锁
- 高级筛选：字段列表从当前数据自动生成，支持包含、等于、有值、无值、数值上下限和区间
- 鼠标筛选：按任意字段点选常见值，或输入数值范围
- 筛选历史：本机自动保存，也可用 GitHub 私有 Gist 在不同浏览器、电脑、手机之间同步
- 表格排序：点击表头升序/降序
- 列显示控制：选择显示哪些列
- 导出功能：当前筛选结果导出为CSV/JSON

网页不再提供“数据来源”下拉筛选。发布数据已经由合并流程综合 ZOL 和 PConline 生成，单条记录会保留 `数据来源` 和 `验证状态` 字段用于查看来源与交叉验证结果；筛选入口面向机型条件本身。

私有 Gist 同步不会在代码中写死任何令牌。页面只在当前浏览器保存你输入的 GitHub Token 和 Gist ID，并在 GitHub 账户下创建或复用 `phones.jiucai.eu.org filter history` 私有 Gist，文件名为 `phone-filter-history.json`。

## 使用方法

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行中关村在线爬虫
python crawl_zol.py --step 1 --time-limit 3600 --max-pages 5

# 3. 运行太平洋电脑网爬虫
python crawl_pconline.py --step 1 --time-limit 3600 --max-pages 5

# 4. 合并数据
python merge_phones.py

# 5. AI搜索BL锁和Root信息
python search_root_info.py --input merged_phones_YYYYMMDD.json
```

### 分步运行

```bash
# 中关村在线 - 只爬取第一步（最多1小时，5页）
python crawl_zol.py --step 1 --time-limit 3600 --max-pages 5

# 中关村在线 - 从断点继续
python crawl_zol.py --step 1 --auto

# 中关村在线 - 后续步骤
python crawl_zol.py --step 2
python crawl_zol.py --step 3

# 太平洋电脑网 - 同样支持分步运行
python crawl_pconline.py --step 1 --time-limit 3600 --max-pages 5
```

### GitHub Actions运行

主爬虫 workflow 不再依赖 GitHub Actions `schedule`，因为 cron 延迟会错过窗口。外部由 cron-job.org 在北京时间约 08:30 和 13:30 调用 `crawl-trigger.yml` 的 `repository_dispatch`，再由它同时拉起中关村在线和太平洋电脑网爬虫。

有效爬取窗口固定为北京时间 08:00-12:30 和 13:00-22:00。无论从 cron-job.org、手动入口还是其它外部入口启动，`custom_scripts/crawl_budget.py` 都会判断当前时间是否在窗口内，并取“当前窗口结束前预留 900 秒”和“GitHub Actions 6 小时限制前预留 1800 秒”两者中更早的截止时间来缩短 `RUN_TIME`；不足 5 分钟则直接成功跳过，避免进度来不及提交。

cron-job.org 配置脚本：

```bash
CRON_JOB_ORG_API_KEY=... GITHUB_DISPATCH_TOKEN=... python custom_scripts/configure_cron_job_org.py
```

该脚本会创建或更新两个 Asia/Shanghai 定时任务：08:30 和 13:30，POST 到 GitHub `repository_dispatch`，payload 为 `event_type=trigger-crawl`。

- 中关村在线：由 `crawl-trigger.yml` 按窗口拉起 `crawl-zol.yml`
- 太平洋电脑网：由 `crawl-trigger.yml` 按窗口拉起 `crawl-pconline.yml`
- 合并分析：每天 UTC 12:30（北京时间 20:30）

两个爬虫脚本在 `--auto` 模式下使用 exit code `10` 表示“本次时间到了但进度已保存”。GitHub Actions 会把这种情况当作正常的断点续爬：先提交 `zol/progress.json` 或 `pconline/progress.json`，再等待下一次窗口继续。workflow 会按 GitHub Actions 总运行时间预留进度提交缓冲，避免 6 小时硬超时导致进度丢失。

进度同步使用 `custom_scripts/git_sync_progress.sh` 执行 `fetch → rebase → push`，遇到失败会打印脱敏后的 Git 错误；cron-job.org 配置脚本也会重试短暂 API 或网络抖动。合并发布中的 Root 信息搜索结果是可选 artifact，缺失时不会阻断 Release 或 Pages 发布。

PConline 进度会记录 `processed_phones` 和 `skipped_phones`，已保存、已判定为旧款、无年份的手机 ID 都会进入处理缓存；断点续爬时会直接跳过这些 ID，避免重复爬同一批 iPhone 旧机型或系列页。

CI 会在 `main` 推送后运行：
- Python 编译检查
- YAML / Shell / JSON / 前端静态文件基础语法检查
- 爬虫 workflow 护栏检查，包括外部触发入口、窗口预算、exit code 10、提交缓冲、进度同步脚本和未定义 step 引用

## 数据字段

### 基础参数（从网站爬取）

| 字段 | 说明 |
|------|------|
| 数据来源 | 单源或双源合并来源 |
| 验证状态 | 单源/双源一致/双源差异 |
| 交叉验证差异 | 双源字段值不一致时记录差异 |
| 品牌 | 手机品牌 |
| 型号 | 手机型号 |
| 上市时间 | 发布/上市时间 |
| 价格 | 电商报价 |
| 处理器 | CPU型号 |
| 内存 | RAM容量 |
| 存储 | ROM容量 |
| 屏幕 | 屏幕尺寸 |
| 屏幕分辨率 | 分辨率 |
| 电池 | 电池容量 |
| 后置摄像头像素 | 后置摄像头 |
| 前置摄像头像素 | 前置摄像头 |
| 机身宽度 | 从宽度或机身尺寸中提取，便于单列筛选 |
| 机身尺寸 | 长宽厚规格，优先使用原站字段，否则由长度/宽度/厚度合成 |
| 摄像头参数 | 后置/前置像素、镜头名称、变焦、传感器、焦距、视频等相机字段汇总 |
| 超广角缩放倍数 | 仅在原始参数明确出现 0.x/1x 或 0.x/1倍等超广角倍率时提取 |

### AI搜索字段

| 字段 | 说明 | 可选值 |
|------|------|--------|
| 是否可解BL锁 | 能否解锁Bootloader | 是/否/免解锁/未知 |
| 是否可root | 能否获取Root权限 | 是/否/未知 |
| 解锁方式 | BL锁解锁方法 | 官方申请/工程线/漏洞利用/未知 |
| root方案 | Root工具 | Magisk/KernelSU/SuperSU/未知 |
| 风险等级 | 操作风险 | 低/中/高/未知 |
| 信息来源 | 信息出处 | XDA/酷安/官方文档/GitHub/未知 |

## 部署方案

### GitHub Pages（推荐）

1. 在仓库 **Settings → Pages → Build and deployment** 中选择 **GitHub Actions**
2. 每次合并分析工作流成功后，网页会自动更新到最新数据；`deploy-pages.yml` 也可独立发布网页外壳并使用最近一份 Release 数据
3. 自定义域名固定为 `phones.jiucai.eu.org`，发布产物会包含 `docs/phones/CNAME`
4. 访问 `https://phones.jiucai.eu.org/`

### 本地预览

```bash
python -m http.server 8000 -d docs/phones
```

然后访问 `http://localhost:8000`

## 注意事项

1. **请求频率**：默认3-5秒间隔，避免被封IP
2. **反爬虫**：使用随机User-Agent、Referer等请求头
3. **断点续传**：进度文件记录已爬取内容，支持中断后继续
4. **数据验证**：两个数据源互相验证，差异会记录在diff文件中
5. **AI搜索**：需要配置 `AI_API_KEY` 环境变量

## 许可证

MIT License
