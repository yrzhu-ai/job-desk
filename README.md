# 作业看台 (Job Desk)

一个用来盯着 Linux / Slurm 集群作业的 Windows 桌面小工具：悬浮球、便利贴、命令行，支持同时管理多个账号。

<!-- 截图可以放在 docs/ 目录，然后在这里引用 -->

## 功能

- **多账号**：任意 Linux 账号都能加（主机 / 端口 / 用户名 / 密码）。自动探测 Slurm 路径（`/opt/slurm/bin`、`/sched/slurm/bin`、`module load slurm` 等），找不到作业系统时自动改看 `top`。
- **作业看板**：运行中 / 排队 / 已完成 / 报错 四栏；排队任务显示已等待时长；可按账号分标签页。
- **悬浮球**：中间是「进行中 / 未完成」，下面是「已完成」，悬停查看分账号明细。
- **命令行**：内置 SSH 终端，鼠标选中即复制、右键粘贴，支持 `bash` / `zsh`。
- **便利贴 / 管家**：今日、本周、本月、学期视图；可改期、设重要度、记录进展、加子任务。
- **皮肤**：4 套深色 + 4 套浅色。
- **自动更新**：每 6 小时检查一次 GitHub Releases，有新版本会弹窗显示这一版改了什么。

## 下载

到 [Releases](https://github.com/yrzhu-ai/job-desk/releases/latest) 下载 `jobdesk.exe`（或对应版本的 exe），双击运行，无需安装 Python。

## 从源码运行

```bash
pip install -r requirements.txt
python app.py
```

## 打包

```bash
python -m PyInstaller --noconfirm --windowed --onefile --name 作业看台 ^
  --icon quill.ico --add-data "quill.ico;." --add-data "update_url.txt;." app.py
```

或者直接双击 `打包成exe.bat`。

## 自动更新怎么工作

`update_url.txt` 里写的是本仓库地址。程序会读取 **最新一个 Release**：

| Release 里的东西 | 程序怎么用 |
|---|---|
| tag（如 `v1.0.15`） | 作为版本号，与本地版本比较 |
| Release 描述 | 弹窗里显示的「这一版改了什么」 |
| `.exe` 附件 | 下载并校验后替换自身 |

> 注意：用 `gh` 上传中文文件名会被改名（`作业看台.exe` → `default.exe`），
> 所以建议附件用英文名，例如 `jobdesk.exe`。程序会挑 Release 里第一个 `.exe`。

## 发布新版本

```bash
# 1. 改 app.py 里的 VERSION
# 2. 打包
python -m PyInstaller ... app.py
# 3. 发 Release（附件用英文名）
gh release create v1.0.15 dist/jobdesk.exe --title "作业看台 1.0.15" --notes "这一版改了什么"
```

已经装了旧版本的用户，最多 6 小时后会看到更新提示（也可以点右上角「检查更新」立刻检查）。

## 目录

| 文件 | 作用 |
|---|---|
| `app.py` | 主窗口、悬浮球、更新弹窗 |
| `jobs.py` | SSH 查询 Slurm / top，解析作业 |
| `plans.py` | 便利贴 / 管家 |
| `shellwin.py` | 内置命令行（终端模拟） |
| `store.py` | 账号、偏好、密码（DPAPI 加密） |
| `theme.py` | 皮肤与配色 |
| `updater.py` | 检查 / 下载 / 替换自身 |
| `winsecret.py` | Windows DPAPI 封装 |

## 许可

暂未指定 License。
