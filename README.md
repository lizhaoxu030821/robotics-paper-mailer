# Cloud Robotics Paper Mailer

这个项目用于每天自动检索机器人运动控制方向论文，并通过 QQ SMTP 发送到指定邮箱。

当前最终方案是：

```text
cron-job.org 定时触发 -> GitHub Actions 运行脚本 -> arXiv 检索论文 -> QQ SMTP 发送邮件
```

电脑关机也可以运行，Codex 也不需要打开，因为触发器和执行环境都在云端。

## 功能

- 每天按北京时间定时触发。
- 自动检索机器人运动控制、腿足机器人、人形机器人、机械臂控制、强化学习控制、MPC、whole-body control 等方向论文。
- 从候选论文中选择相关性较高且未发送过的论文。
- 邮件中包含英文标题、作者、发布日期、论文链接、PDF 链接或附件、摘要、推荐理由等信息。
- 如果 PDF 可公开下载且小于 18 MB，会尽量作为附件发送。
- 使用 `data/sent_papers.json` 记录已经发送过的论文，避免每天重复推送同一篇。
- arXiv API 返回 `429` 限流时会自动等待并重试。

## 0. 准备工作

你需要准备：

1. GitHub 账号。
2. 一个 GitHub 私有仓库，例如 `robotics-paper-mailer`。
3. QQ 邮箱，并开启 SMTP/IMAP 服务。
4. QQ 邮箱 SMTP 授权码。注意：授权码不是 QQ 登录密码。
5. cron-job.org 账号。

## 1. 上传项目文件到 GitHub

在 GitHub 新建一个私有仓库，例如：

```text
robotics-paper-mailer
```

上传或创建以下文件，路径必须保持不变：

```text
README.md
scripts/send_daily_robotics_paper.py
.github/workflows/daily-paper.yml
```

建议仓库保持 Private，因为这是个人自动化任务。

## 2. 配置 GitHub Secrets

进入仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

添加 3 个 Secrets：

| Secret 名称 | 值 |
| --- | --- |
| `QQ_SMTP_USER` | 你的 QQ 邮箱，例如 `2365318481@qq.com` |
| `QQ_SMTP_AUTH_CODE` | 你的 QQ 邮箱 SMTP 授权码 |
| `MAIL_TO` | 收件邮箱，例如 `2365318481@qq.com` |

不要把 SMTP 授权码写进代码、README、截图或聊天记录里。

## 3. GitHub Actions workflow

`.github/workflows/daily-paper.yml` 推荐使用下面这种形式：

```yaml
name: Daily Robotics Paper Email

on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  send-paper:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Send daily paper email
        env:
          QQ_SMTP_USER: ${{ secrets.QQ_SMTP_USER }}
          QQ_SMTP_AUTH_CODE: ${{ secrets.QQ_SMTP_AUTH_CODE }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
        run: python scripts/send_daily_robotics_paper.py

      - name: Commit sent paper history
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/sent_papers.json
          git diff --cached --quiet || git commit -m "Record sent paper"
          git push
```

说明：

- `workflow_dispatch` 表示允许外部或手动触发。
- `permissions: contents: write` 是必须的，因为脚本发送成功后要把 `data/sent_papers.json` 提交回仓库。
- `data/sent_papers.json` 用来记录已经发过的论文，避免重复发送。

## 4. 手动测试 GitHub Actions

进入 GitHub 仓库：

```text
Actions -> Daily Robotics Paper Email -> Run workflow
```

手动运行一次。

如果运行成功并收到邮件，说明：

- GitHub Secrets 配置正确。
- Python 脚本能正常运行。
- QQ SMTP 能正常发信。

如果失败，点进失败的 run，查看红叉步骤的日志。

## 5. 为什么不用 GitHub 自带 schedule

GitHub Actions 支持：

```yaml
on:
  schedule:
    - cron: "45 1 * * *"
```

但实际测试中，GitHub 的 `schedule` 可能延迟，刚创建或刚修改 workflow 后甚至可能漏触发。为了更稳定地按北京时间触发，最终方案改为使用 cron-job.org 定时调用 GitHub API。

## 6. 创建 GitHub Fine-grained Token

cron-job.org 需要一个 GitHub Token 来触发 workflow。

进入：

```text
GitHub 头像 -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens
```

生成新 Token：

```text
Token name: robotics-paper-mailer-trigger
Repository access: Only select repositories
Selected repository: robotics-paper-mailer
```

Repository permissions 只需要添加：

```text
Actions: Read and write
```

其他权限不要加。

生成后复制 Token。不要把 Token 发给别人，不要截图，不要提交进仓库。

如果怀疑 Token 泄露，立刻 Revoke 并重新生成。

## 7. 配置 cron-job.org

打开：

```text
https://cron-job.org
```

创建一个新的 Cronjob。

### Common 配置

Title：

```text
Daily Robotics Paper Email
```

URL：

```text
https://api.github.com/repos/<GitHub用户名>/<仓库名>/actions/workflows/daily-paper.yml/dispatches
```

本项目示例：

```text
https://api.github.com/repos/lizhaoxu030821/robotics-paper-mailer/actions/workflows/daily-paper.yml/dispatches
```

Enable job：

```text
开启
```

Execution schedule：

```text
Every day at 09:45
```

Time zone：

```text
Asia/Shanghai
```

cron-job.org 使用你设置的时区，所以这里直接填北京时间，不需要换算 UTC。

### Advanced 配置

Request method：

```text
POST
```

Headers：

| Key | Value |
| --- | --- |
| `Authorization` | `Bearer <你的 GitHub Token>` |
| `Accept` | `application/vnd.github+json` |
| `X-GitHub-Api-Version` | `2022-11-28` |
| `Content-Type` | `application/json` |

Request body：

```json
{"ref":"main"}
```

Timeout 可以保持默认，例如 30 秒。

## 8. 测试 cron-job.org

在 cron-job.org 页面点击：

```text
TEST RUN
```

如果配置正确：

1. cron-job.org 会调用 GitHub API。
2. GitHub Actions 页面会出现一条新的 workflow 运行记录。
3. 运行成功后，你会收到邮件。

常见返回：

| 状态 | 含义 |
| --- | --- |
| `204` | 成功触发 GitHub Actions。 |
| `401` | Token 错误、过期或 Authorization Header 写错。 |
| `403` | Token 权限不够，检查 Actions: Read and write。 |
| `404` | 仓库名、用户名、workflow 文件名或 Token 仓库访问范围错误。 |
| `422` | Request body 或 ref 分支错误，检查 `{"ref":"main"}`。 |

测试成功后，点击：

```text
CREATE
```

保存任务。

## 9. 最终日常运行方式

保存后，系统会按下面链路运行：

```text
每天北京时间 09:45
cron-job.org 自动触发 GitHub workflow_dispatch
GitHub Actions 运行 Python 脚本
脚本检索论文并跳过已发送论文
QQ SMTP 发送邮件
GitHub Actions 提交 data/sent_papers.json
```

电脑不用开机，Codex 不用打开。

## 10. 去重机制

脚本会读取：

```text
data/sent_papers.json
```

这个文件记录已经发送过的论文 URL。

每次运行时：

1. 从 arXiv 检索候选论文。
2. 按相关性和发布时间排序。
3. 跳过 `data/sent_papers.json` 中已经存在的论文。
4. 发送未发送过的最高分论文。
5. 发送成功后，把论文记录写入 `data/sent_papers.json`。
6. GitHub Actions 自动提交这个记录。

如果所有候选论文都已经发送过，脚本会回退到当前最高分论文。这通常只会在短时间连续测试很多次，或检索条件太窄时发生。

## 11. arXiv 429 限流

如果 GitHub Actions 日志里出现：

```text
HTTP Error 429
```

说明 arXiv API 认为请求太频繁。

脚本已经加入：

- 429 自动等待重试。
- 每组 arXiv 查询之间暂停几秒。

正常每天运行一次基本不会触发限流。连续手动测试时建议间隔几分钟。

## 12. 修改发送时间

不需要改 GitHub Actions。

只需要进入 cron-job.org，修改 Execution schedule。

例如每天北京时间 09:45：

```text
Every day at 09:45
Time zone: Asia/Shanghai
```

保存即可。

## 13. 修改论文方向

编辑：

```text
scripts/send_daily_robotics_paper.py
```

主要修改两个变量：

```python
QUERIES = [...]
KEYWORDS = {...}
```

例如改成具身智能/机器人基础模型方向：

```python
QUERIES = [
    "cat:cs.RO AND all:embodied",
    "cat:cs.RO AND all:foundation model",
    "cat:cs.AI AND all:robot",
    "cat:cs.LG AND all:robotics",
]

KEYWORDS = {
    "embodied ai": 12,
    "vision-language-action": 12,
    "robot foundation model": 12,
    "manipulation": 8,
    "generalist policy": 8,
}
```

## 14. 每天发送 2 篇或更多

当前脚本默认每天发送 1 篇。

如果要每天发送多篇，可以二次开发：

1. 把 `find_best_paper` 改为 `find_best_papers(sent_urls, count)`。
2. 返回未发送过的 Top N 篇论文。
3. 邮件正文中循环展示多篇论文。
4. 可以只给第一篇附 PDF，其余提供链接，避免附件太大。
5. 发送成功后，把多篇论文都写入 `data/sent_papers.json`。

## 15. 其他二次开发想法

- 按星期轮换主题：周一腿足机器人，周二机械臂控制，周三强化学习控制。
- 增加 OpenReview、Semantic Scholar、Crossref 等来源。
- 接入 OpenAI API，把英文摘要改写成更自然的中文技术解读。
- 增加黑名单关键词，排除不想看的方向。
- 增加机构偏好，例如优先 MIT、CMU、ETH、Berkeley、Stanford、清华、北大、上海交大等。
- 增加周报模式：每天发 1 篇，周末汇总本周论文。
- 增加备用通知：如果 GitHub Actions 失败，发一封失败提醒邮件。

## 16. 日常维护

- QQ SMTP 授权码失效：更新 GitHub Secret `QQ_SMTP_AUTH_CODE`。
- GitHub Token 失效：重新生成 Token，并更新 cron-job.org 的 Authorization Header。
- 想换发送时间：只改 cron-job.org。
- 想换论文方向：改 Python 脚本里的 `QUERIES` 和 `KEYWORDS`。
- 想重新允许旧论文被推荐：删除或清空 `data/sent_papers.json`。

## 17. 最终结论

最终系统已经实现云端自动发送：

```text
cron-job.org 负责定时
GitHub Actions 负责执行
Python 脚本负责检索和发信
GitHub 仓库负责保存历史记录
QQ SMTP 负责发送邮件
```

只要 cron-job.org 任务启用、GitHub Token 有效、GitHub Secrets 正确、QQ SMTP 授权码有效，就会每天按设置时间自动发送论文邮件。
