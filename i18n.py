"""Two-language interface. Chinese strings stay in the source; this maps them to English.

The app was written with Chinese literals everywhere, so instead of touching every
call site we translate widget options (text/title), menus, tree headings and the
common dialog helpers. Anything missing from the table simply stays Chinese.
"""

from __future__ import annotations

import ctypes
import re
import tkinter as tk
from tkinter import messagebox, ttk

LANGUAGES = (("auto", "跟随系统"), ("zh", "中文"), ("en", "English"))

# Chinese -> English, matched exactly.
EN: dict[str, str] = {
    # window / chrome
    "作业看台": "Job Desk",
    "未知": "Unknown",
    "未命名": "unnamed",
    "无密码": "no password",
    "未连上": "offline",
    # skins
    "深夜": "Night",
    "海洋": "Ocean",
    "纸页": "Paper",
    "新绿": "Leaf",
    "落日": "Sunset",
    "极简": "Minimal",
    "樱花": "Sakura",
    "高对比": "Contrast",
    "当前": "current",
    "确定": "OK",
    "状态": "Status",
    "重要性": "Priority",
    # planner extras
    "完成档案": "Done archive",
    "15 分钟": "15 min",
    "30 分钟": "30 min",
    "1 小时": "1 hour",
    "2 小时": "2 hours",
    "不提醒": "Off",
    # dialogs / hints
    "更新": "Update",
    "设置": "Settings",
    "密码留空表示不修改。": "Leave the password empty to keep it unchanged.",
    "已经填过 Token（留空表示不修改）。": "A GitHub token is already saved (leave empty to keep it).",
    "还没有填 Token（可选）。": "No GitHub token yet (optional).",
    "可选。填一个 GitHub Token，更新检查的额度会从每小时 60 次提升到 5000 次。在 GitHub → Settings → Developer settings 生成，权限只需 public_repo（或只读）。留空表示不修改。": "Optional. A GitHub token raises the update-check quota from 60 to 5000 requests per hour. Create one under GitHub -> Settings -> Developer settings; public_repo (or read-only) is enough. Leave empty to keep the current one.",
    "这个账号还没有密码。": "This account has no saved password yet.",
    "能用密码登录的 Linux 都可以加。有 Slurm 就看作业；没有作业系统时自动改看 top。密码只加密留在这台电脑。程序只查询，不提交也不取消。附加 PATH 可选，squeue 不在默认 PATH 时再填目录，多个用英文冒号，不要空格。修改时密码留空表示不改。": "Any Linux account you can log into with a password works. With Slurm you get the job board; without a scheduler the app falls back to top. The password is encrypted and kept on this PC only. The app only reads state - it never submits or cancels jobs. Extra PATH is optional: set it when squeue is not on the default PATH; separate folders with colons, no spaces. Leave the password empty when editing to keep it.",
    "使用快速回答，不开启深度思考。只发送作业状态或你写下的那段话，不发送账号密码。": "Uses fast answers with no deep reasoning. Only job state or the paragraph you typed is sent - never account passwords.",
    "第一个注册的用户，会用上这台电脑里已经保存的账号和便利贴。": "The first account you register inherits the accounts and notes already saved on this PC.",
    "GitHub 接口暂时限流，过一会儿再试（不影响使用）。": "GitHub API is rate limited right now; try again later (nothing is broken).",
    "这个发行版里没有 .exe 文件。": "This release has no .exe asset.",
    "这个发行版没有 tag，无法比较版本。": "This release has no tag, so versions cannot be compared.",
    "更新地址跳到了不安全的链接。": "The update URL redirected to an insecure link.",
    "更新清单不是一份 json。": "The manifest is not valid JSON.",
    "更新清单格式不对。": "The manifest has an unexpected shape.",
    "更新清单太大。": "The manifest is too large.",
    "下载到的文件不像这个程序。": "The downloaded file does not look like this program.",
    "Linux 作业，和自己要做的事。只查询，不提交也不取消。": "Linux jobs and your own to-dos. Read only: nothing is submitted or cancelled.",
    "作业": "Jobs",
    "管家": "Planner",
    "账号密码": "Accounts",
    "简洁": "Compact",
    "完整": "Full",
    "立即刷新": "Refresh",
    "悬浮球": "Ball",
    "隐藏完成": "Hide done",
    "隐藏报错": "Hide failed",
    "检查更新": "Check updates",
    "文字": "Text",
    "皮肤": "Theme",
    "退出登录": "Sign out",
    "语言": "Language",
    "跟随系统": "System",
    # tabs / counters
    "全部": "All",
    "运行中": "Running",
    "排队中": "Queued",
    "排队": "Queued",
    "已完成": "Done",
    "报错": "Failed",
    "完成": "Done",
    "运行 / 排队 / 完成 / 报错": "Run / Queue / Done / Fail",
    "个作业": "jobs",
    "搜索": "Search",
    "结束作业近": "Ended within",
    "天": "days",
    "稍后": "Later",
    "上次刷新": "Last refresh",
    "下次自动刷新": "Next refresh",
    "正在刷新…": "Refreshing…",
    "正在连接各账号…": "Connecting accounts…",
    "还没有账号": "No account yet",
    "还没有刷新": "Not refreshed yet",
    # columns
    "账号": "Account",
    "作业号": "Job ID",
    "作业名": "Job name",
    "状态": "State",
    "已运行": "Elapsed",
    "时限": "Time limit",
    "分区": "Partition",
    "核数": "CPUs",
    "内存": "Memory",
    "节点/原因": "Node / reason",
    "提交时间": "Submitted",
    "排队时长": "Queued for",
    "开始时间": "Started",
    "结束时间": "Ended",
    "退出码": "Exit code",
    "数据来源": "Source",
    "工作目录": "Work dir",
    "备注": "Note",
    # empty states
    "还没有账号。先填写下面的主机、端口、用户名和密码。": "No account yet. Fill in host, port, user and password below.",
    "这里还没有": "Nothing here",
    "还没有进展": "No progress yet",
    "还没有子任务。双击这行可以写。": "No steps yet. Double-click this row to add one.",
    "没有符合当前筛选的作业。": "No jobs match the current filter.",
    "没有符合搜索的作业。": "No jobs match your search.",
    "这一类里没有作业。": "No jobs in this category.",
    "这个账号下没有符合条件的作业。": "No matching jobs for this account.",
    "没有账号结果。": "No account results.",
    "正在读取各账号的作业…": "Reading jobs from each account…",
    "没有读到作业。\n原因在窗口最下面。": "No jobs read.\nSee the reason at the bottom.",
    # setup card
    "填写 Linux 账号": "Add a Linux account",
    "主机": "Host",
    "端口": "Port",
    "用户名": "User",
    "密码": "Password",
    "显示名": "Label",
    "附加 PATH": "Extra PATH",
    "保存账号": "Save account",
    "打开账号窗口": "Open accounts",
    "密码只加密留在这台电脑。显示名和附加 PATH 可以空着。": "The password is encrypted and kept on this PC only. Label and extra PATH are optional.",
    # account dialog
    "账号1 到 账号n": "Accounts",
    "显示密码": "Show password",
    "新建": "New",
    "保存": "Save",
    "删除": "Delete",
    "测试连接": "Test connection",
    "清除此主机旧密钥": "Forget host key",
    "打开配置目录": "Open config folder",
    "选中左侧账号可修改，或点「新建」。": "Pick an account on the left, or click New.",
    "连接成功。": "Connected.",
    "正在连接…": "Connecting…",
    # detail / context menu
    "查看详情": "Details",
    "写备注": "Add note",
    "进入命令行": "Open shell",
    "复制作业号": "Copy job ID",
    "复制作业名": "Copy job name",
    "删除这条": "Remove this",
    "不再显示这条": "Hide this job",
    "复制全部": "Copy all",
    "保存备注": "Save note",
    "关闭": "Close",
    "退出": "Quit",
    "稍后处理": "Later",
    "现在查看": "View now",
    "全部稍后处理": "Defer all",
    "作业跑完了": "Jobs finished",
    "可以现在打开，或先放着稍后处理。": "Open one now, or deal with them later.",
    "这些完成提醒先留着": "Finished jobs kept for later",
    "现在查看": "View now",
    "移除": "Remove",
    "没有还在列表里的稍后任务。": "Nothing left in the list.",
    # settings
    "接口地址": "API base",
    "模型": "Model",
    "API Key": "API Key",
    "显示密钥": "Show key",
    "清除密钥": "Clear key",
    "密钥留空表示不修改。": "Leave the key empty to keep the current one.",
    "还没有密钥。": "No key yet.",
    "已保存。": "Saved.",
    "密钥已清除。": "Key cleared.",
    # updates
    "发现新版本": "New version available",
    "这一版改了什么": "What changed",
    "当前版本": "Current version",
    "现在更新": "Update now",
    "跳过这个版本": "Skip this version",
    "检查更新": "Check updates",
    "正在问…": "Asking…",
    "问 DeepSeek": "Ask DeepSeek",
    "发送": "Send",
    "按当前账号和搜索结果提问。只发送作业状态，不发送密码。": "Ask about the current account and search results. Only job state is sent, never passwords.",
    "例如：哪些报错了？排队的原因是什么？": "e.g. Which jobs failed? Why are they queued?",
    # planner
    "未完成": "Open",
    "今日": "Today",
    "进行中": "Doing",
    "本周": "This week",
    "本月": "This month",
    "本学期": "This term",
    "档案": "Archive",
    "垃圾桶": "Trash",
    "列表": "List",
    "便利贴": "Notes",
    "提醒": "Remind",
    "选择日期": "Pick date",
    "加到这一天": "Add to this day",
    "加到本周": "Add to this week",
    "加到本月": "Add to this month",
    "加到本学期": "Add to this term",
    "加一条": "Add",
    "整理成任务": "Split into tasks",
    "密钥": "Key",
    "写下一段话，DeepSeek 会整理成可以直接做的任务列表。": "Write a paragraph; DeepSeek turns it into actionable tasks.",
    "待做": "To do",
    "暂停": "Paused",
    "普通": "Normal",
    "重要": "Important",
    "紧急": "Urgent",
    "改期": "Reschedule",
    "自定义日期…": "Custom date…",
    "今天": "Today",
    "明天": "Tomorrow",
    "后天": "In 2 days",
    "三天后": "In 3 days",
    "一周后": "In 1 week",
    "下周一": "Next Monday",
    "两周后": "In 2 weeks",
    "本月末": "End of month",
    "上移一层": "Move up",
    "下移一层": "Move down",
    "放到最前": "Bring to front",
    "放到最后": "Send to back",
    "编辑内容": "Edit",
    "改标题": "Rename",
    "放进垃圾桶": "Move to trash",
    "恢复": "Restore",
    "彻底删除": "Delete forever",
    "加下一步": "Add next step",
    "记下": "Save",
    "加分支": "Add branch",
    "去掉": "Remove",
    "这些完成提醒先留着": "Finished jobs kept for later",
    # shell
    "配色": "Colors",
    "正在登录…": "Connecting…",
    "连接已结束": "Connection closed",
    "发送失败，连接可能已经断开。": "Send failed; the connection may be gone.",
    "已登录": "Connected",
    "目录": "Dir",
    "家目录": "home",
}

# Dynamic messages: (regex on the Chinese text, English template with \1..\9).
PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^运行 (\d+)，排队 (\d+)，完成 (\d+)，报错 (\d+)$"), r"Run \1 · Queue \2 · Done \3 · Fail \4"),
    (re.compile(r"^账号(\d+)$"), r"Account \1"),
    (re.compile(r"^账号(\d+)\s+(.+)$"), r"Account \1 \2"),
    (re.compile(r"^上次刷新 (.+)$"), r"Last refresh \1"),
    (re.compile(r"^下次自动刷新 ([0-9:]+)$"), r"Next refresh \1"),
    (re.compile(r"^近 (\d+) 天没有作业。$"), r"No jobs in the last \1 day(s)."),
    (re.compile(r"^(\d+) 个账号没连上$"), r"\1 account(s) offline"),
    (re.compile(r"^(\d+) 个账号还没有密码$"), r"\1 account(s) without a password"),
    (re.compile(r"^更新 (.+)$"), r"Update \1"),
    (re.compile(r"^发现新版本 (.+)$"), r"New version \1"),
    (re.compile(r"^当前版本 (.+)$"), r"Current \1"),
    (re.compile(r"^排 (.+)$"), r"queued \1"),
    (re.compile(r"^已复制 (\d+) 个字符$"), r"Copied \1 characters"),
    (re.compile(r"^还有 (\d+) 件，打开管家可以看全。$"), r"And \1 more; open the planner to see all."),
    (re.compile(r"^(\d+) 个作业$"), r"\1 jobs"),
    (re.compile(r"^更新地址返回了 (\d+)。$"), r"Update server returned \1."),
    (re.compile(r"^已经是最新版本 (.+)。$"), r"You are on the latest version (\1)."),
    (re.compile(r"^没有连上更新地址：(.+)$"), r"Could not reach the update server: \1"),
]


class Language:
    def __init__(self) -> None:
        self.code = "zh"

    @property
    def english(self) -> bool:
        return self.code == "en"


language = Language()


def system_language() -> str:
    try:
        lang = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except Exception:
        return "zh"
    return "zh" if (lang & 0x3FF) == 0x04 else "en"


def resolve(choice: str) -> str:
    return system_language() if (choice or "auto") == "auto" else ("en" if choice == "en" else "zh")


def tr(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    if not language.english:
        return text
    exact = EN.get(text)
    if exact is not None:
        return exact
    stripped = text.strip()
    if stripped != text:
        inner = EN.get(stripped)
        if inner is not None:
            lead = text[: len(text) - len(text.lstrip())]
            return lead + inner
    for pattern, template in PATTERNS:
        if pattern.match(text):
            return pattern.sub(template, text)
    return text


def _translate_option(node, option: str) -> None:
    try:
        value = node.cget(option)
    except tk.TclError:
        return
    if not isinstance(value, str) or not value:
        return
    raw = getattr(node, "_i18n_raw_" + option, None)
    if raw is None:
        raw = value
        setattr(node, "_i18n_raw_" + option, raw)
    new = tr(raw)
    if new != value:
        try:
            node.configure(**{option: new})
        except tk.TclError:
            pass


def _translate_menu(menu: tk.Menu) -> None:
    try:
        last = menu.index("end")
    except tk.TclError:
        return
    if last is None:
        return
    for index in range(last + 1):
        try:
            kind = menu.type(index)
        except tk.TclError:
            continue
        if kind == "separator":
            continue
        try:
            label = menu.entrycget(index, "label")
        except tk.TclError:
            continue
        raw = getattr(menu, f"_i18n_entry_{index}", None)
        if raw is None:
            raw = label
            setattr(menu, f"_i18n_entry_{index}", raw)
        new = tr(raw)
        if new != label:
            try:
                menu.entryconfigure(index, label=new)
            except tk.TclError:
                pass


def apply(widget) -> None:
    """Translate every widget text/title under the given window."""
    try:
        children = widget.winfo_children()
    except tk.TclError:
        return
    for option in ("text", "title"):
        _translate_option(widget, option)
    if isinstance(widget, ttk.Treeview):
        try:
            for column in widget["columns"]:
                heading = widget.heading(column, "text")
                raw = getattr(widget, f"_i18n_col_{column}", None)
                if raw is None:
                    raw = heading
                    setattr(widget, f"_i18n_col_{column}", raw)
                new = tr(raw)
                if new != heading:
                    widget.heading(column, text=new)
        except tk.TclError:
            pass
    if isinstance(widget, tk.Menu):
        _translate_menu(widget)
    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        try:
            current = widget.title()
            raw = getattr(widget, "_i18n_title", None)
            if raw is None:
                raw = current
                widget._i18n_title = raw
            new = tr(raw)
            if new != current:
                widget.title(new)
        except tk.TclError:
            pass
    for child in children:
        apply(child)


def install() -> None:
    """Patch dialogs and new windows so later UI is translated too."""
    if getattr(install, "_done", False):
        return
    install._done = True

    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askstring"):
        original = getattr(messagebox, name, None)
        if original is None:
            continue

        def wrapper(*args, _original=original, **kwargs):
            translated = tuple(tr(arg) if isinstance(arg, str) else arg for arg in args)
            return _original(*translated, **kwargs)

        setattr(messagebox, name, wrapper)

    original_init = tk.Toplevel.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if language.english:
            try:
                self.after(15, lambda: apply(self))
            except tk.TclError:
                pass

    tk.Toplevel.__init__ = patched_init


def counts(run: int, wait: int, done: int, bad: int) -> str:
    """One line summary used in the status bar and tab subtitles."""
    if language.english:
        return f"Run {run} · Queue {wait} · Done {done} · Fail {bad}"
    return f"运行 {run}，排队 {wait}，完成 {done}，报错 {bad}"


def _self_test() -> None:
    language.code = "en"
    assert tr("账号密码") == "Accounts"
    assert tr("去掉") == "Remove"
    assert tr("账号3") == "Account 3"
    assert tr("上次刷新 12:00:00") == "Last refresh 12:00:00"
    assert tr("运行 6，排队 7，完成 0，报错 1") == "Run 6 · Queue 7 · Done 0 · Fail 1"
    assert tr("完全没翻译的句子") == "完全没翻译的句子"
    language.code = "zh"
    assert tr("账号密码") == "账号密码"
    assert resolve("auto") in {"zh", "en"}
    print("i18n self-test ok", len(EN))


if __name__ == "__main__":
    _self_test()
