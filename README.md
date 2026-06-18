# Cloud Robotics Paper Mailer

这个项目用于在 GitHub Actions 云端每天在你设置的北京时间自动检索机器人运动控制方向论文，并通过 QQ SMTP 发到你的邮箱。电脑关机也可以运行，因为任务由 GitHub 云端执行。

## 使用步骤

1. 在 GitHub 新建一个私有仓库，例如 `robotics-paper-mailer`。
2. 上传本目录里的所有文件，保持 `.github/workflows/daily-paper.yml` 和 `scripts/send_daily_robotics_paper.py` 路径不变。
3. 进入仓库 `Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`，添加下面 3 个 Secrets：

| Secret 名称 | 值 |
| --- | --- |
| `QQ_SMTP_USER` | `你的 QQ 邮箱` |
| `QQ_SMTP_AUTH_CODE` | 你的 QQ 邮箱 SMTP 授权码 |
| `MAIL_TO` | `你的 QQ 邮箱` |

4. 进入仓库 `Actions` 页面，启用 workflows。
5. 打开 `Daily Robotics Paper Email` workflow，点击 `Run workflow` 手动测试一次。
6. 正常后，GitHub 会每天在设置的时间发送邮件到你的邮箱。

## 说明

- 脚本只使用 Python 标准库，不需要安装依赖。
- 当前云端版本使用 arXiv 公开 API 作为稳定论文来源。IEEE、Google Scholar、ScienceDirect 等来源通常需要 API、订阅或会受反爬限制，不适合作为无账号的定时云端任务直接抓取。
- 如果 PDF 可公开下载且小于 18 MB，邮件会附带 PDF；否则邮件中会提供 PDF 链接。
- QQ SMTP 授权码不要写进代码，也不要发到聊天里，只放在 GitHub Actions Secrets 中。

## 手动触发

在 GitHub 仓库的 `Actions` 页面选择 `Daily Robotics Paper Email`，点击 `Run workflow`。这会立刻发一封测试邮件。
