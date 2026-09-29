# 软件版本发布与自动更新

软件固定从 `lizhaoxu030821/robotics-paper-mailer` 的 GitHub Releases 检查更新。朋友配置的个人论文仓库不会影响软件更新源。

## 发布新版本

1. 修改 `desktop_app.py` 中的 `APP_VERSION`，例如从 `1.3.0` 改为 `1.4.0`。
2. 将本次代码、`FEATURES.md`、spec 文件和 `.github/workflows/release-desktop.yml` 提交到官方仓库的 `main` 分支。
3. 在 GitHub 仓库进入 `Actions -> Build Desktop Release -> Run workflow`。
4. 输入与软件版本一致的标签，例如 `v1.4.0`，运行工作流。
5. 工作流会在 Windows Runner 上打包并验证 EXE，然后创建 GitHub Release，附件名称固定为 `机器人论文云端助手.exe`。
6. 打开 Release 页面，检查更新说明和附件后再通知用户。

也可以通过推送 `v*` Git 标签触发同一工作流。

## 用户更新流程

1. 软件启动约 2.5 秒后自动检查最新版。
2. 发现更高版本后显示版本号与 Release 更新说明。
3. 用户点击“下载并更新”。
4. 软件从固定官方仓库下载 EXE，并校验 GitHub 返回的文件大小和 SHA-256 digest（若 Release API 提供 digest）。
5. 下载完成后软件退出，更新脚本覆盖当前 EXE 并重新启动。
6. `%APPDATA%\CloudRoboticsPaperMailer` 中的主题配置、GitHub 登录状态和本地历史不会被覆盖。

## 发布要求

- `APP_VERSION` 与 Release 标签必须一致，例如 `APP_VERSION = "1.4.0"` 对应 `v1.4.0`。
- Release 不能是 Draft 或 Pre-release，否则 `/releases/latest` 不会将其作为正式最新版。
- 附件最好保持名称 `机器人论文云端助手.exe`。客户端找不到该名称时会回退选择第一个 `.exe` 文件。
- 不要在朋友的个人论文仓库发布桌面软件版本；更新只使用固定官方仓库。
- 发布前应运行语法检查、内置脚本验证和一次界面启动测试。
