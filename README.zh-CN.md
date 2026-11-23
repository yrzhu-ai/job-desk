# 作业看台 (Job Desk)

[English](README.md) · **简体中文**

[![最新版本](https://img.shields.io/github/v/release/yrzhu-ai/job-desk?sort=semver)](https://github.com/yrzhu-ai/job-desk/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![平台](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)](#运行环境)

一个用来盯 **Linux / Slurm 集群作业** 的 Windows 桌面小工具：悬浮球、SSH 命令行、便利贴管家。
支持任意多个账号，不需要针对某个集群做配置。

<!-- 截图可以放到 docs/ 目录，然后在这里引用 -->

## 功能

- **任意 Linux 账号**：填写主机 / 端口 / 用户名 / 密码即可。自动探测 Slurm
  （`/opt/slurm/bin`、`/sched/slurm/bin`、`module load slurm` 等）；没有调度系统时自动改看 `top`。
- **作业看板**：运行中 / 排队 / 已完成 / 报错 四栏，每个账号一个标签页，排队任务显示已等待时长，也可切换成完整表格。
- **悬浮球**：中间大数字是「进行中 / 未完成」，下面小字是「已完成」，悬停可看分账号明细。
- **命令行**：内置 SSH 终端，鼠标选中即复制、右键粘贴（MobaXterm 习惯），兼容 `bash` / `zsh`。
- **便利贴管家**：今日 / 本周 / 本月 / 本学期视图，支持改期、重要度、进展记录和子任务。
- **皮肤**：4 套深色 + 4 套浅色。
- **中英文双语**：跟随系统 / 中文 / English，运行中随时切换。
- **自动更新**：每 24 小时检查一次 GitHub Releases，更新前显示这一版改了什么。

## 运行环境

- Windows 10 / 11（64 位）
- 能通过 SSH 连到集群
- 集群需要有 `squeue` / `sacct`；没有的话程序会自动改看 `top`

## 下载

到 **[Releases](https://github.com/yrzhu-ai/job-desk/releases/latest)** 下载最新的 `jobdesk.exe`，双击运行即可。
不用安装，也不需要 Python。

> Windows SmartScreen 可能会提示未知发布者，点「更多信息 → 仍要运行」即可。
> 每个版本的 SHA-256 都附在对应的 Release 里。

## 使用

1. **账号密码** → 填写主机、端口、用户名、密码。密码用当前 Windows 用户的 DPAPI 加密，
   不会离开这台电脑。
2. **作业** → 看板会自动刷新；需要立刻更新时点「立即刷新」。
3. **悬浮球** → 把窗口收成右下角一个小圆球，始终置顶。
4. **命令行** → 为某个账号打开 SSH 终端；选中文字自动复制，右键粘贴。
5. **管家** → 写一段话，让 DeepSeek 整理成任务（可选，需要在设置里填 API Key）。

## 自动更新

`update_url.txt` 里写的是本仓库地址。每次检查会读取**最新的 Release**：

| Release 里的东西 | 用途 |
|---|---|
| tag（如 `v1.0.17`） | 版本号比较 |
| Release 描述 | 弹窗里的「这一版改了什么」 |
| `.exe` 附件 | 下载文件（按大小和 SHA-256 校验） |

也可以改成自己的 JSON 清单，格式见 `update_url.txt` 里的注释。

## 从源码运行

```bash
pip install -r requirements.txt
python app.py            # 直接运行
```

打包成单个 exe：

```bash
python build.py          # 生成 dist/作业看台.exe，带版本信息
```

或者直接双击 `打包成exe.bat`。`build.py` 会读取 `app.py` 里的 `VERSION`，
生成 `version_info.txt`，并关闭 UPX 压缩。

## Windows 可能提示风险

这个 exe **没有数字签名**，别人第一次运行时 Windows SmartScreen 会提示
*「Windows 已保护你的电脑」*：

> 更多信息 → **仍要运行**

想确认下载的文件没被掉包，可以做两件事：

- 对比同一 Release 里 `jobdesk.exe.sha256` 的哈希：
  `certutil -hashfile jobdesk.exe SHA256`
- 右键 exe → 属性 → 详细信息，应显示 *Job Desk* 和对应版本号

如果杀毒软件误报（360/火绒偶尔会把 PyInstaller 单文件打包当作可疑程序），
欢迎提 Issue 并附版本号。为了减少误报，构建时已经关闭了 UPX 压缩。

如果将来要对外大规模分发、希望彻底去掉这个提示，就需要**代码签名证书**
（OV/EV 证书，或微软 Azure Trusted Signing）——这是需要实名审核的付费服务，
参见[微软签名文档](https://learn.microsoft.com/azure/trusted-signing/)。

## 发布新版本

```bash
# 1. 改 app.py 里的 VERSION 并提交
# 2. 打 tag 推送
git tag v1.0.17
git push origin main --tags
```

GitHub Actions 会自动构建 exe、计算 SHA-256 并发布 Release
（见 [`.github/workflows/release.yml`](.github/workflows/release.yml)）。
手动触发工作流时只上传构建产物，不发版。

## 目录结构

| 文件 | 作用 |
|---|---|
| `app.py` | 主窗口、悬浮球、更新弹窗 |
| `jobs.py` | SSH 查询 Slurm / top 并解析 |
| `plans.py` | 便利贴管家 |
| `shellwin.py` | 内置命令行（终端模拟） |
| `store.py` | 账号、偏好、DPAPI 加密的密码 |
| `theme.py` | 皮肤与配色 |
| `i18n.py` | 中英文界面 |
| `updater.py` | 检查 / 下载 / 替换自身 |
| `winsecret.py` | Windows DPAPI 封装 |

## 参与

欢迎提 Issue 和 PR。改动尽量小而明确，说明用户能看到的变化；有截图更好。

## 许可

[MIT](LICENSE) © 2026 yrzhu-ai
