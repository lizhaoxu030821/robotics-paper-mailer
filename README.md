# Robotics Paper Mailer

每天自动从 arXiv 检索机器人运动控制相关论文，选择一篇未推送过的高相关论文，发送到 QQ 邮箱，同步到 Zotero，并写入 Obsidian outbox，供 Obsidian Agent Dashboard 后续导入阅读、精读和整理。

当前主流程保持稳定优先：检索查询和关键词权重仍在 Python 脚本中硬编码，不再使用 Obsidian 偏好配置同步到 GitHub Actions。

## 当前链路

```text
cron-job.org 或手动触发
-> GitHub Actions workflow_dispatch
-> scripts/send_daily_robotics_paper.py
-> arXiv 检索和打分
-> QQ 邮箱发送
-> Zotero collection 同步
-> Obsidian outbox 写入
-> GitHub Actions 提交 sent_papers.json 和 obsidian-outbox
```

本地电脑不需要开机，Codex 不需要打开。只有从 Obsidian 点击 `Import outbox` 时，才需要本地 Obsidian 去拉取 GitHub outbox 并导入 Vault。

## 主要功能

- 从 arXiv 检索机器人运动控制、腿足机器人、人形机器人、loco-manipulation、whole-body control、强化学习控制、MPC 等方向论文。
- 根据关键词、arXiv 分类和发布时间打分，选出当天最相关的新论文。
- 发送 QQ 邮件，正文包含标题、作者、日期、链接、PDF、摘要和推荐理由。
- 尽量下载 PDF 并作为邮件附件发送。
- 同步论文条目到 Zotero 指定 collection。
- 优先上传 Zotero imported PDF 附件；如果上传失败，会删除坏附件并创建 arXiv PDF 链接附件兜底。
- 生成 Obsidian outbox Markdown：
  - `Agent Dashboard/Outbox/Zotero Intake`
  - `Agent Dashboard/Outbox/Runner/Requests`
- GitHub Actions 成功后自动提交：
  - `data/sent_papers.json`
  - `obsidian-outbox`
- 如果没有新论文，会输出 `NO_NEW_PAPER` 并正常退出，不再重复发送旧论文。

## 去重策略

脚本会统一使用 canonical arXiv ID 去重。

例如：

```text
2606.29209v1
2606.29209v2
```

会被视为同一篇论文：

```text
2606.29209
```

去重来源包括：

- `data/sent_papers.json`
- Zotero collection 里已有论文
- `obsidian-outbox` 里已经写入过的论文

如果候选论文全部已存在，脚本会打印：

```text
NO_NEW_PAPER: All ranked candidate papers were already sent or already exist in Zotero.
```

然后正常结束 workflow。

## GitHub Actions

当前 workflow 文件：

```text
.github/workflows/daily-paper.yml
```

当前触发方式：

```yaml
on:
  workflow_dispatch:
```

也就是说，GitHub 仓库本身只开放手动/API 触发。定时推荐交给 cron-job.org 调用 GitHub API，这样比 GitHub 自带 schedule 更可控。

workflow 当前超时：

```yaml
timeout-minutes: 6
```

这是为了避免 arXiv、Zotero、SMTP 或 GitHub 网络抖动时拖很久。

## 必需 GitHub Secrets

进入仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

需要配置：

| Secret | 用途 |
| --- | --- |
| `QQ_SMTP_USER` | QQ 发件邮箱 |
| `QQ_SMTP_AUTH_CODE` | QQ 邮箱 SMTP 授权码，不是 QQ 登录密码 |
| `MAIL_TO` | 收件邮箱 |
| `ZOTERO_API_KEY` | Zotero API key |
| `ZOTERO_USER_ID` | Zotero user ID |
| `ZOTERO_COLLECTION_NAME` | 目标 Zotero collection 名称 |

不要把任何 secret 写进代码、README、截图或聊天记录。

## cron-job.org 触发

推荐用 cron-job.org 每天定时调用 GitHub workflow dispatch API。

URL 示例：

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

如果返回 `204`，说明触发成功。

## Obsidian outbox

GitHub Actions 会写入：

```text
obsidian-outbox/ResearchVault/legged-robot-motion-control/Agent Dashboard/Outbox
```

本地 Obsidian Agent Dashboard 的 `Today -> Import outbox` 会：

1. 尝试运行本地同步脚本拉取 GitHub 最新 outbox。
2. 如果 GitHub 暂时连不上，使用本地缓存 outbox 继续导入。
3. 把文件复制到正式目录：

```text
Agent Dashboard/Zotero Intake
Agent Dashboard/Runner/Requests
```

导入时会把 frontmatter 状态从：

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

## 本地 outbox 同步脚本

本地同步脚本不提交到 GitHub，路径通常是：

```text
D:\Projects\robotics-paper-mailer\local-sync\sync-obsidian-outbox.ps1
```

它负责：

- `git pull` 当前仓库
- 复制 `obsidian-outbox` 到 Obsidian Vault
- 写入本地日志
- GitHub 拉取失败时不中断导入，而是继续使用本地缓存

## Zotero PDF 修复脚本

新增本地维修工具：

```text
scripts/repair_zotero_pdfs.py
```

用途：扫描指定 Zotero collection 中 imported PDF 附件是否真的存在于本地 `storage`，如果缺失，可以从 arXiv 重新下载。

默认是 dry-run，只扫描不下载：

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

默认 Zotero 目录：

```text
C:\Users\<用户名>\Zotero
```

可以手动指定：

```powershell
python scripts/repair_zotero_pdfs.py --zotero-dir "C:\Users\Li_Zhaoxu\Zotero" --collection-id 9
```

这个脚本只读 Zotero sqlite 数据库，不修改数据库；`--apply` 时只会把缺失的 PDF 文件下载到对应的 Zotero `storage` 文件夹。

## 常用命令

检查本地仓库状态：

```powershell
cd D:\Projects\robotics-paper-mailer
git status
```

手动运行主脚本需要配置环境变量，不建议在本地随便跑，因为它会发邮件、写 Zotero、写 outbox。

检查 Zotero PDF 缺失：

```powershell
python scripts/repair_zotero_pdfs.py --collection-id 9
```

同步本地 Obsidian outbox：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\Projects\robotics-paper-mailer\local-sync\sync-obsidian-outbox.ps1"
```

## 维护原则

- 主流程稳定优先，不要频繁大改 GitHub Actions 和发邮件逻辑。
- 检索偏好暂时保持硬编码，主要修改：

```text
scripts/send_daily_robotics_paper.py
```

里的：

```python
QUERIES = [...]
KEYWORDS = {...}
```

- 不再使用 `paper_preferences/config.yml` 或 Obsidian 偏好同步进入 GitHub Actions 主流程。
- Obsidian 前端可以作为阅读和导入工具，但不要直接自动污染正式知识库。
- Zotero 修复脚本作为维修工具，默认 dry-run，确认后再 `--apply`。

## 当前状态

最近关键修复：

```text
115e9e3 Avoid duplicate papers and broken Zotero attachments
820d20f Add Zotero PDF repair script
```

系统目前已经实现：

- QQ 邮件每日论文推送
- Zotero collection 同步
- imported PDF 优先上传和坏附件清理
- arXiv PDF 链接附件兜底
- canonical arXiv ID 去重
- Obsidian outbox 写入
- Obsidian Agent Dashboard 手动导入
- Zotero 本地 PDF 缺失扫描与修复

下一步推荐：

- 增加主脚本 dry-run 模式：只显示当天会选哪篇，不发邮件、不写 Zotero、不写 Obsidian。
- 在 Obsidian Agent Dashboard 中继续打磨阅读状态、草稿区和知识库升格流程。
