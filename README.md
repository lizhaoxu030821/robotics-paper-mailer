# Robotics Paper Mailer

这是一个“每日机器人论文自动分发和整理”项目。它会从 arXiv 检索机器人运动控制相关论文，选择一篇未推送过的高相关论文，发送到 QQ 邮箱，同步到 Zotero，并写入 Obsidian outbox，供 Obsidian Agent Dashboard 后续导入阅读、精读和整理。

这份 README 的目标不是只给人看，而是让用户把 README 和项目文件交给 AI 后，AI 可以指导或直接帮助完成配置。

## 给 AI 的执行说明

如果你是接手本项目的 AI，请先按下面顺序工作：

1. 读取仓库文件，重点检查：
   - `.github/workflows/daily-paper.yml`
   - `scripts/send_daily_robotics_paper.py`
   - `scripts/repair_zotero_pdfs.py`
   - `data/sent_papers.json`
   - `obsidian-outbox/`
2. 不要要求用户把 secret 明文发到聊天里。引导用户在 GitHub Secrets、Zotero 网页、QQ 邮箱后台、cron-job.org 页面中填写。
3. 不要优先大改主流程。当前稳定策略是保留 Python 脚本中的硬编码检索逻辑。
4. 先完成最小可运行配置：
   - GitHub Secrets
   - GitHub Actions 手动运行
   - cron-job.org 定时触发
   - Zotero collection 同步
   - Obsidian outbox 导入
5. 配置完成后，用测试清单验证，而不是凭感觉说“应该可以”。

## 项目能力

当前系统已经实现：

- arXiv 自动检索和打分。
- QQ 邮箱每日推送论文。
- Zotero collection 自动归档。
- Zotero imported PDF 优先上传。
- Zotero PDF 上传失败时删除坏附件，并创建 arXiv PDF 链接附件兜底。
- canonical arXiv ID 去重。
- `NO_NEW_PAPER` 正常退出，不重复发送旧论文。
- Obsidian outbox 写入。
- Obsidian Agent Dashboard 手动导入 Today。
- 本地 Zotero PDF 缺失扫描和修复脚本。

当前主流程保持稳定优先：检索查询和关键词权重仍在 Python 脚本中硬编码，不再使用 `paper_preferences/config.yml` 或 Obsidian 偏好同步进入 GitHub Actions 主流程。

## 系统链路

```text
cron-job.org 或手动触发
-> GitHub Actions workflow_dispatch
-> scripts/send_daily_robotics_paper.py
-> arXiv 检索和打分
-> QQ 邮箱发送
-> Zotero collection 同步
-> Obsidian outbox 写入
-> GitHub Actions 提交 data/sent_papers.json 和 obsidian-outbox
```

本地电脑不需要开机，Codex 不需要打开。只有从 Obsidian 点击 `Import outbox` 时，才需要本地 Obsidian 拉取 GitHub outbox 并导入 Vault。

## 文件结构

```text
robotics-paper-mailer/
├─ .github/
│  └─ workflows/
│     └─ daily-paper.yml
├─ data/
│  └─ sent_papers.json
├─ obsidian-outbox/
│  └─ ResearchVault/
│     └─ legged-robot-motion-control/
│        └─ Agent Dashboard/
│           └─ Outbox/
├─ scripts/
│  ├─ send_daily_robotics_paper.py
│  └─ repair_zotero_pdfs.py
└─ README.md
```

本地可能还有一个不提交到 GitHub 的目录：

```text
local-sync/
└─ sync-obsidian-outbox.ps1
```

它用于 Obsidian 本地导入 outbox。

## 需要用户准备的信息

AI 接手配置时，需要让用户准备这些信息，但不要让用户把敏感值直接贴到聊天里：

| 项目 | 用途 | 是否敏感 |
| --- | --- | --- |
| GitHub 仓库地址 | 放置本项目并运行 Actions | 否 |
| QQ 发件邮箱 | SMTP 发信 | 否 |
| QQ SMTP 授权码 | SMTP 登录 | 是 |
| 收件邮箱 | 接收每日论文 | 否 |
| Zotero API key | 写入 Zotero | 是 |
| Zotero user ID | Zotero API 地址 | 否 |
| Zotero collection 名称 | 论文归档目标 | 否 |
| Obsidian Vault 路径 | 本地导入 outbox | 否 |
| cron-job.org 触发时间 | 每天自动运行 | 否 |
| GitHub fine-grained token | cron-job.org 触发 Actions | 是 |

## GitHub Secrets 配置

进入 GitHub 仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

添加：

| Secret | 说明 |
| --- | --- |
| `QQ_SMTP_USER` | QQ 发件邮箱 |
| `QQ_SMTP_AUTH_CODE` | QQ 邮箱 SMTP 授权码，不是 QQ 登录密码 |
| `MAIL_TO` | 收件邮箱 |
| `ZOTERO_API_KEY` | Zotero API key |
| `ZOTERO_USER_ID` | Zotero user ID |
| `ZOTERO_COLLECTION_NAME` | 目标 Zotero collection 名称 |

AI 应提醒用户：这些 secret 只能填在 GitHub Secrets 页面，不要写进代码、README、截图或聊天记录。

## Zotero 配置

1. 打开 Zotero API key 页面：

```text
https://www.zotero.org/settings/keys
```

2. 创建 private key，建议权限：

```text
Personal Library: Allow library access
Allow write access: enabled
Allow notes access: optional
Default Group Permissions: None
```

3. 把 API key 填入 GitHub Secret：

```text
ZOTERO_API_KEY
```

4. 同一页面会显示 user ID，填入：

```text
ZOTERO_USER_ID
```

5. 在 Zotero 中创建或确认目标 collection，例如：

```text
机器人运控论文
```

6. 把 collection 名称原样填入：

```text
ZOTERO_COLLECTION_NAME
```

名称必须完全一致，包括空格和中文。

## GitHub Actions 配置

当前 workflow 文件是：

```text
.github/workflows/daily-paper.yml
```

当前触发方式：

```yaml
on:
  workflow_dispatch:
```

这表示 GitHub 仓库本身只开放手动或 API 触发。定时推荐交给 cron-job.org 调用 GitHub API。

当前 workflow 关键配置：

```yaml
permissions:
  contents: write

jobs:
  send-paper:
    runs-on: ubuntu-latest
    timeout-minutes: 6
```

`contents: write` 必须保留，因为 workflow 成功后会提交：

```text
data/sent_papers.json
obsidian-outbox
```

## 手动测试 GitHub Actions

进入：

```text
Actions -> Daily Robotics Paper Email -> Run workflow
```

运行后检查：

1. Actions 是否成功。
2. QQ 邮箱是否收到论文。
3. Zotero collection 是否新增论文。
4. 仓库是否产生自动提交：

```text
Record sent paper and Obsidian outbox
```

5. `obsidian-outbox` 是否新增当天文件。

如果 Actions 成功但没有邮件，检查 QQ SMTP secret。
如果有邮件但 Zotero 没新增，检查 Zotero secret 和 Actions 日志。
如果没有新论文但 workflow 成功，查看是否输出 `NO_NEW_PAPER`。

## cron-job.org 定时触发

推荐用 cron-job.org 每天定时调用 GitHub workflow dispatch API。

URL：

```text
https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily-paper.yml/dispatches
```

本项目示例：

```text
https://api.github.com/repos/lizhaoxu030821/robotics-paper-mailer/actions/workflows/daily-paper.yml/dispatches
```

Method：

```text
POST
```

Headers：

| Key | Value |
| --- | --- |
| `Authorization` | `Bearer <GitHub fine-grained token>` |
| `Accept` | `application/vnd.github+json` |
| `X-GitHub-Api-Version` | `2022-11-28` |
| `Content-Type` | `application/json` |

Body：

```json
{"ref":"main"}
```

如果 cron-job.org 测试返回 `204`，说明触发成功。

GitHub fine-grained token 需要给目标仓库：

```text
Actions: Read and write
```

不要给多余权限。

## Obsidian outbox 配置

GitHub Actions 会写入：

```text
obsidian-outbox/ResearchVault/legged-robot-motion-control/Agent Dashboard/Outbox
```

Obsidian Agent Dashboard 的 `Today -> Import outbox` 会把文件导入到：

```text
Agent Dashboard/Zotero Intake
Agent Dashboard/Runner/Requests
```

导入时会把 frontmatter 从：

```yaml
status: outbox
```

改成：

```yaml
status: intake
```

或：

```yaml
status: queued
```

## 本地 Obsidian 同步脚本模板

如果用户希望在 Obsidian 里点 `Import outbox` 时自动拉取 GitHub 最新 outbox，可以在本地创建：

```text
D:\Projects\robotics-paper-mailer\local-sync\sync-obsidian-outbox.ps1
```

模板：

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = "D:\Projects\robotics-paper-mailer"
$sourceOutbox = Join-Path $repoRoot "obsidian-outbox\ResearchVault\legged-robot-motion-control\Agent Dashboard\Outbox"
$targetAgentDashboard = "D:\文档\Obsidian Vault\ResearchVault\legged-robot-motion-control\Agent Dashboard"
$logPath = Join-Path $repoRoot "local-sync\sync-obsidian-outbox.log"

function Write-SyncLog {
	param([string]$Message)
	$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
	Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Invoke-LoggedCommand {
	param(
		[string]$FilePath,
		[string[]]$Arguments
	)

	$output = & $FilePath @Arguments 2>&1
	foreach ($line in $output) {
		Write-SyncLog "${FilePath}: $line"
	}
	if ($LASTEXITCODE -ne 0) {
		throw "$FilePath failed with exit code $LASTEXITCODE"
	}
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null
Set-Location -LiteralPath $repoRoot
Write-SyncLog "Start sync."

try {
	Invoke-LoggedCommand "git" @("-c", "http.version=HTTP/1.1", "pull", "--ff-only")
	Write-SyncLog "Pulled latest outbox from GitHub."
} catch {
	Write-SyncLog "WARNING: Git pull failed; continuing with the local cached outbox."
	Write-SyncLog "WARNING: $($_.Exception.Message)"
}

if (-not (Test-Path -LiteralPath $sourceOutbox)) {
	Write-SyncLog "No outbox folder yet: $sourceOutbox"
	return
}

if (-not (Test-Path -LiteralPath $targetAgentDashboard)) {
	New-Item -ItemType Directory -Force -Path $targetAgentDashboard | Out-Null
	Write-SyncLog "Created target Agent Dashboard folder."
}

Copy-Item -LiteralPath $sourceOutbox -Destination $targetAgentDashboard -Recurse -Force
Write-SyncLog "Copied outbox to Vault: $targetAgentDashboard"
```

AI 需要根据用户实际路径替换：

- `$repoRoot`
- `$targetAgentDashboard`
- `ResearchVault/legged-robot-motion-control`

然后在 Agent Dashboard 插件设置里把 `Outbox sync script` 指向该脚本。

## Zotero PDF 修复脚本

脚本：

```text
scripts/repair_zotero_pdfs.py
```

用途：扫描 Zotero collection 中 imported PDF 附件是否真的存在于本地 `storage`，如果缺失，可以从 arXiv 重新下载。

默认 dry-run，只扫描不下载：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9
```

实际修复：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9 --apply
```

限制修复数量：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9 --apply --limit 3
```

指定 Zotero 目录：

```powershell
python scripts/repair_zotero_pdfs.py --zotero-dir "C:\Users\Li_Zhaoxu\Zotero" --collection-id 9
```

这个脚本只读 Zotero sqlite 数据库，不修改数据库；`--apply` 时只会下载缺失 PDF 到对应的 Zotero `storage` 文件夹。

## 去重策略

脚本统一使用 canonical arXiv ID 去重。

例如：

```text
2606.29209v1
2606.29209v2
```

会视为同一篇：

```text
2606.29209
```

去重来源包括：

- `data/sent_papers.json`
- Zotero collection 已有论文
- `obsidian-outbox` 已经写入过的论文

如果候选论文全部已存在，脚本会正常输出：

```text
NO_NEW_PAPER: All ranked candidate papers were already sent or already exist in Zotero.
```

## 修改论文方向

当前不建议引入复杂外部配置。要修改检索方向，编辑：

```text
scripts/send_daily_robotics_paper.py
```

主要修改：

```python
QUERIES = [...]
KEYWORDS = {...}
```

示例：

```python
QUERIES = [
    "cat:cs.RO AND all:locomotion",
    "cat:cs.RO AND all:humanoid",
    "cat:cs.RO AND all:manipulation",
]

KEYWORDS = {
    "whole-body": 12,
    "locomotion": 10,
    "humanoid": 10,
    "model predictive control": 11,
}
```

AI 修改后必须提醒用户：频繁大改检索逻辑可能导致推送质量波动，先小范围调整并观察几天。

## 常用验证命令

检查仓库状态：

```powershell
cd D:\Projects\robotics-paper-mailer
git status
```

查看最近提交：

```powershell
git log --oneline -5
```

检查 Zotero PDF 缺失：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9
```

手动同步本地 Obsidian outbox：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\Projects\robotics-paper-mailer\local-sync\sync-obsidian-outbox.ps1"
```

不要随便在本地运行主脚本，除非已经配置环境变量并明确知道它会：

- 发邮件
- 写 Zotero
- 写 Obsidian outbox
- 修改 `data/sent_papers.json`

## 故障排查

### GitHub Actions 没启动

检查：

- cron-job.org 返回码是否为 `204`
- GitHub token 是否有 `Actions: Read and write`
- URL 中 owner、repo、workflow 文件名是否正确
- body 是否是 `{"ref":"main"}`

### 邮件没收到

检查：

- `QQ_SMTP_USER`
- `QQ_SMTP_AUTH_CODE`
- `MAIL_TO`
- QQ 邮箱是否开启 SMTP
- Actions 日志里是否有 SMTP 报错

### Zotero 没新增

检查：

- `ZOTERO_API_KEY` 是否有 write 权限
- `ZOTERO_USER_ID` 是否正确
- `ZOTERO_COLLECTION_NAME` 是否和 Zotero collection 完全一致
- Actions 日志里是否出现 `Zotero sync failed`

### Zotero 有条目但 PDF 打不开

运行：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9
```

如果发现缺失，再运行：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9 --apply
```

### Obsidian Import outbox 没导入

检查：

- GitHub Actions 是否提交了 `obsidian-outbox`
- 本地仓库是否能 `git pull`
- `local-sync/sync-obsidian-outbox.ps1` 路径是否正确
- Agent Dashboard 设置里的 `Outbox sync script` 是否指向该脚本
- Vault 中是否出现：

```text
Agent Dashboard/Outbox/Zotero Intake
Agent Dashboard/Outbox/Runner/Requests
```

## AI 接手时的推荐任务提示词

用户可以把下面这段发给 AI：

```text
请读取这个 README 和项目文件，帮我完成 Robotics Paper Mailer 的配置。目标是：
1. GitHub Actions 可以手动运行成功。
2. QQ 邮箱能收到每日论文。
3. Zotero 指定 collection 能新增论文。
4. GitHub 能提交 data/sent_papers.json 和 obsidian-outbox。
5. Obsidian Agent Dashboard 可以通过 Import outbox 导入论文。

请不要让我把 secret 明文发到聊天里，只告诉我应该去哪个网页或设置页填写。
请优先保持当前稳定主流程，不要引入新的偏好配置系统。
配置完成后，请用 README 里的验证清单逐项检查。
```

## 当前关键提交

```text
115e9e3 Avoid duplicate papers and broken Zotero attachments
820d20f Add Zotero PDF repair script
```

## 后续推荐

- 增加主脚本 dry-run 模式：只显示当天会选哪篇，不发邮件、不写 Zotero、不写 Obsidian。
- 在 Obsidian Agent Dashboard 中继续打磨阅读状态、草稿区和知识库升格流程。
- 如果未来重新做 Obsidian 前端偏好配置，先只编辑本地偏好文件，不要直接接入 GitHub Actions 主流程。
