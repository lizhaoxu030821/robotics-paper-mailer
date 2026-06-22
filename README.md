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
| `QQ_SMTP_USER` | 你的 QQ 邮箱，例如 `23456789@qq.com` |
| `QQ_SMTP_AUTH_CODE` | 你的 QQ 邮箱 SMTP 授权码 |
| `MAIL_TO` | 收件邮箱，例如 `12345678@qq.com` |

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

---

# 1.1 版本：Zotero 同步增强

1.1 版本在 1.0 的“每日邮件推送”基础上，新增了 Zotero 自动归档能力。现在系统不仅会把每天推荐的论文发到 QQ 邮箱，还会尝试把同一篇论文同步保存到 Zotero 的指定 Collection 中，例如：

```text
机器人运控论文
```

## 1.1 新增功能

- 邮件发送成功后，自动连接 Zotero Web API。
- 自动查找 Zotero 中名为 `机器人运控论文` 的 Collection。
- 自动创建论文条目，保存标题、作者、摘要、发布日期、arXiv 链接、分类标签等元数据。
- 如果 PDF 下载成功，会优先尝试把 PDF 上传为 Zotero 附件。
- 如果 PDF 上传失败，例如 Zotero 存储空间不足、上传接口临时失败，会自动降级为 PDF 链接附件。
- Zotero 同步失败不会阻断邮件发送，失败信息会写入 GitHub Actions 日志。
- 原有去重逻辑仍然保留，继续通过 `data/sent_papers.json` 避免重复推送同一篇论文。

## 1.1 最终链路

1.0 版本链路：

```text
cron-job.org -> GitHub Actions -> arXiv -> QQ SMTP -> QQ 邮箱
```

1.1 版本链路：

```text
cron-job.org -> GitHub Actions -> arXiv -> QQ SMTP -> QQ 邮箱
                                      -> Zotero Web API -> 机器人运控论文 Collection
```

也就是说，Zotero 是在 GitHub Actions 脚本运行过程中同步写入的，不依赖本地电脑，也不需要 Zotero 桌面端保持打开。只要 Zotero 桌面端之后正常同步，就能看到新增条目。

## 1.1 需要新增的 GitHub Secrets

在 GitHub 仓库中进入：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

在原有 3 个 Secrets 基础上，新增下面 3 个：

| Secret 名称 | 含义 |
| --- | --- |
| `ZOTERO_API_KEY` | Zotero 官网生成的 API Key |
| `ZOTERO_USER_ID` | Zotero API 页面显示的数字 User ID |
| `ZOTERO_COLLECTION_NAME` | 要保存到的 Zotero 文件夹名称，例如 `机器人运控论文` |

完整 Secrets 列表如下：

| Secret 名称 | 用途 |
| --- | --- |
| `QQ_SMTP_USER` | QQ 发件邮箱 |
| `QQ_SMTP_AUTH_CODE` | QQ 邮箱 SMTP 授权码 |
| `MAIL_TO` | 收件邮箱 |
| `ZOTERO_API_KEY` | Zotero API 鉴权 |
| `ZOTERO_USER_ID` | 指定 Zotero 个人库 |
| `ZOTERO_COLLECTION_NAME` | 指定 Zotero Collection |

不要把 `ZOTERO_API_KEY` 写进代码、README、截图或聊天记录里。

## Zotero API Key 获取方式

打开 Zotero API Keys 页面：

```text
https://www.zotero.org/settings/keys
```

点击：

```text
Create new private key
```

推荐配置：

```text
Key Name: robotics-paper-mailer
Personal Library: Allow library access
Allow write access: 勾选
Allow notes access: 可不勾选
Default Group Permissions: None
```

创建完成后复制 API Key，并添加到 GitHub Secret：

```text
ZOTERO_API_KEY
```

同一页面会显示：

```text
Your user ID for use in API calls is xxxxxxxx
```

把这个数字添加为：

```text
ZOTERO_USER_ID
```

## Zotero Collection 准备

在 Zotero 桌面端或网页版中新建一个 Collection，名称例如：

```text
机器人运控论文
```

然后在 GitHub Secrets 中添加：

```text
ZOTERO_COLLECTION_NAME = 机器人运控论文
```

名称要完全一致。比如你 Zotero 里叫 `机器人运动控制论文`，Secret 里也必须写 `机器人运动控制论文`，不能少字或多空格。

## workflow 需要增加的环境变量

`.github/workflows/daily-paper.yml` 中，`Send daily paper email` 步骤需要把 Zotero Secrets 传给 Python 脚本：

```yaml
- name: Send daily paper email
  env:
    QQ_SMTP_USER: ${{ secrets.QQ_SMTP_USER }}
    QQ_SMTP_AUTH_CODE: ${{ secrets.QQ_SMTP_AUTH_CODE }}
    MAIL_TO: ${{ secrets.MAIL_TO }}
    ZOTERO_API_KEY: ${{ secrets.ZOTERO_API_KEY }}
    ZOTERO_USER_ID: ${{ secrets.ZOTERO_USER_ID }}
    ZOTERO_COLLECTION_NAME: ${{ secrets.ZOTERO_COLLECTION_NAME }}
  run: python scripts/send_daily_robotics_paper.py
```

## 1.1 代码实现思路

核心修改在：

```text
scripts/send_daily_robotics_paper.py
```

新增了几类函数：

```text
zotero_enabled()
zotero_request()
zotero_json_request()
zotero_find_collection_key()
zotero_create_item()
zotero_create_imported_attachment()
zotero_create_link_attachment()
zotero_upload_attachment_file()
sync_to_zotero()
```

运行流程如下：

1. 脚本先从 arXiv 检索并筛选论文。
2. 下载论文 PDF。
3. 发送 QQ 邮件。
4. 调用 `sync_to_zotero(paper, pdf_path)`。
5. 查找 `ZOTERO_COLLECTION_NAME` 对应的 Collection。
6. 在 Zotero 中创建论文条目。
7. 如果有 PDF，优先上传 PDF 附件。
8. 如果 PDF 上传失败，改为创建 PDF 链接附件。
9. 写入 `data/sent_papers.json`，避免后续重复推荐。

## 如何测试 1.1 功能

手动触发一次 GitHub Actions：

```text
Actions -> Daily Robotics Paper Email -> Run workflow
```

运行完成后检查：

1. QQ 邮箱是否收到邮件。
2. Zotero 的 `机器人运控论文` 文件夹是否新增论文条目。
3. GitHub Actions 日志中是否出现：

```text
ZOTERO_SYNCED: <论文标题>
```

如果 Zotero 没有新增，展开 GitHub Actions 的 `Send daily paper email` 步骤，看是否有：

```text
Zotero sync failed: ...
```

如果出现 PDF 上传失败，但 Zotero 条目存在且有 PDF 链接附件，一般可以接受。这说明 Zotero Storage 上传失败，但链接兜底逻辑生效了。

## 常见问题

### 1. 邮件发送成功，但 Zotero 没有新增

优先检查 GitHub Actions 日志中的：

```text
Zotero sync failed: ...
```

常见原因：

- `ZOTERO_API_KEY` 没有写权限。
- `ZOTERO_USER_ID` 填错。
- `ZOTERO_COLLECTION_NAME` 和 Zotero 中的 Collection 名称不一致。
- Zotero API 临时不可用。

### 2. Zotero 条目有了，但没有 PDF 文件

可能原因：

- PDF 下载失败。
- Zotero Storage 空间不足。
- Zotero 文件上传接口临时失败。

脚本会自动降级为 PDF 链接附件。也就是说，最差情况下 Zotero 里仍能看到论文条目和 PDF 链接。

### 3. 想保存到别的 Zotero 文件夹

只需要改 GitHub Secret：

```text
ZOTERO_COLLECTION_NAME
```

例如从：

```text
机器人运控论文
```

改成：

```text
腿足机器人论文
```

前提是 Zotero 里已经存在这个 Collection。

### 4. 想按不同方向保存到不同文件夹

可以二次开发一个主题到 Collection 的映射，例如：

```python
TOPIC_COLLECTIONS = {
    "locomotion": "腿足机器人论文",
    "manipulation": "机械臂论文",
    "reinforcement learning": "强化学习控制论文",
}
```

然后根据论文命中的关键词选择不同的 Zotero Collection。

### 5. 想只保存到 Zotero，不再发邮件

可以在 `main()` 中注释或删除：

```python
send_email(paper, pdf_path)
```

保留：

```python
sync_to_zotero(paper, pdf_path)
```

不过更推荐保留邮件，因为邮件相当于每日提醒；Zotero 负责长期归档。

### 6. 想只创建 Zotero 条目，不上传 PDF

可以把：

```python
sync_to_zotero(paper, pdf_path)
```

改成：

```python
sync_to_zotero(paper, None)
```

这样 Zotero 里会创建论文条目和 PDF 链接，不会上传 PDF 文件，能节省 Zotero Storage 空间。

### 7. 想换成 Zotero Group Library

当前实现写入个人库：

```text
https://api.zotero.org/users/<ZOTERO_USER_ID>/...
```

如果要写入 Group Library，需要改成：

```text
https://api.zotero.org/groups/<GROUP_ID>/...
```

同时 Zotero API Key 要有对应 Group 的 Read/Write 权限。

## 1.1 版本维护建议

- 定期检查 Zotero Storage 空间，避免 PDF 上传失败。
- 不要删除 `data/sent_papers.json`，否则可能重新推送旧论文。
- 如果 Zotero API Key 泄露，立即在 Zotero 官网删除旧 Key 并生成新 Key。
- 如果只是改保存文件夹，优先改 `ZOTERO_COLLECTION_NAME`，不要改代码。
- 如果要多方向多文件夹，建议引入 `config.yml`，不要继续硬编码。

## 1.1 版本总结

1.0 版本解决的是“每天自动发现论文并发邮件”。

1.1 版本进一步解决“论文长期归档和文献管理”的问题：

```text
邮件负责提醒
Zotero 负责沉淀
GitHub Actions 负责执行
cron-job.org 负责定时
```

这使项目从一个邮件脚本升级成了一个轻量级的机器人领域科研文献自动化系统。

作者：李兆旭

时间：2026.6.18

地点：哈尔滨工业大学

联系方式：18908340080@163.com
