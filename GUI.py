import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
SCRIPT_PATH = PROJECT_ROOT / "ticket_script.py"


class TicketHelperGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("周杰伦大麦抢票助手")
        self._configure_window()
        self.window.configure(bg="#f4f7fb")
        self.window.resizable(True, True)

        self.process = None
        self.schedule_after_id = None
        self.output_queue = queue.Queue()

        self._configure_style()
        self._build_ui()
        self.load_config()
        self.window.after(120, self._poll_output)

    def _configure_window(self):
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        width = min(max(int(screen_width * 0.9), 1320), 1720)
        height = min(max(int(screen_height * 0.86), 760), 1080)
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2 - 10, 0)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _configure_style(self):
        self.style = ttk.Style()
        self.style.configure("TLabel", font=("Arial", 13), foreground="#1f2937")
        self.style.configure("Muted.TLabel", font=("Arial", 12), foreground="#64748b")
        self.style.configure("Title.TLabel", font=("Arial", 30, "bold"), foreground="#172033")
        self.style.configure("Section.TLabelframe.Label", font=("Arial", 14, "bold"), foreground="#172033")
        self.style.configure("TButton", font=("Arial", 13), padding=(14, 10))
        self.style.configure("Primary.TButton", font=("Arial", 14, "bold"), padding=(18, 12))
        self.style.configure("TEntry", font=("Arial", 13), padding=6)

    def _build_ui(self):
        root = tk.Frame(self.window, bg="#f4f7fb")
        root.pack(fill=tk.BOTH, expand=True, padx=26, pady=22)
        root.columnconfigure(0, weight=5)
        root.columnconfigure(1, weight=4)
        root.rowconfigure(1, weight=1)

        header = tk.Frame(root, bg="#f4f7fb")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="周杰伦大麦抢票助手", style="Title.TLabel", background="#f4f7fb").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="目标：周杰伦北京站 2026-06-15 14:00 二开。今天先填配置，明天开售前一键启动等待开抢。",
            style="Muted.TLabel",
            background="#f4f7fb",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        config_frame = ttk.LabelFrame(root, text="1. 抢票配置", style="Section.TLabelframe", padding=16)
        config_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        config_frame.columnconfigure(1, weight=1)

        self.event_name = self._add_entry(config_frame, 0, "演出名称", "用于确认当前目标，默认是周杰伦北京站")
        self.target_url = self._add_entry(
            config_frame,
            1,
            "演出链接",
            "大麦移动端演出详情页链接，通常是 m.damai.cn/damai/detail/...",
        )
        self.auto_buy_time = self._add_entry(config_frame, 2, "启动时间", "建议比开抢早 5-10 分钟；格式：2026-06-15 13:55:00")
        self.ticket_num = self._add_entry(config_frame, 3, "购票数量", "要买几张票，例如 1 或 2")
        self.date = self._add_entry(config_frame, 4, "日期优先级", "例如 1 或 1,2。数字表示页面上第几个日期")
        self.session = self._add_entry(config_frame, 5, "场次优先级", "例如 1 或 1,2。数字表示页面上第几个场次")
        self.price = self._add_entry(config_frame, 6, "票档优先级", "例如 1 或 2,1。数字表示页面上第几个票档")
        self.viewer_person = self._add_entry(config_frame, 7, "观影人序号", "例如 1 或 1,2。数字表示确认页上第几个观影人")
        self.damai_url = self._add_entry(config_frame, 8, "大麦首页", "默认 https://www.damai.cn/")

        hint = ttk.Label(
            config_frame,
            text="小提示：优先级里的数字都从 1 开始。比如票档填 2,1 表示先试第 2 个票档，不行再试第 1 个。",
            style="Muted.TLabel",
        )
        hint.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        action_frame = ttk.LabelFrame(root, text="2. 运行", style="Section.TLabelframe", padding=16)
        action_frame.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        action_frame.rowconfigure(9, weight=1)

        self.status_var = tk.StringVar(value="状态：尚未检查")
        ttk.Label(action_frame, textvariable=self.status_var, font=("Arial", 15, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )

        self.save_button = ttk.Button(action_frame, text="保存配置", command=self.save_config)
        self.save_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)

        self.login_test_button = ttk.Button(action_frame, text="登录 / 刷新 Cookie", command=self.login_test)
        self.login_test_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)

        self.start_button = ttk.Button(action_frame, text="提前启动等待开抢", command=self.start_script)
        self.start_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 6))

        self.schedule_button = ttk.Button(action_frame, text="定时启动等待", command=self.schedule_script)
        self.schedule_button.grid(row=4, column=0, sticky="ew", padx=(0, 8), pady=6)

        self.cancel_schedule_button = ttk.Button(action_frame, text="取消定时", command=self.cancel_schedule, state=tk.DISABLED)
        self.cancel_schedule_button.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=6)

        self.stop_button = ttk.Button(action_frame, text="停止脚本", command=self.stop_script, state=tk.DISABLED)
        self.stop_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)

        tools = ttk.LabelFrame(action_frame, text="辅助检查", padding=10)
        tools.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 6))
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        self.check_button = ttk.Button(tools, text="检查环境", command=self.check_environment)
        self.check_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.target_test_button = ttk.Button(tools, text="打开演出页", command=self.open_target_test)
        self.target_test_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(
            action_frame,
            text="开售前提前启动即可；提交订单后需要人工付款。",
            style="Muted.TLabel",
            justify=tk.LEFT,
        ).grid(row=7, column=0, columnspan=2, sticky="nw", pady=(12, 0))

        log_frame = ttk.LabelFrame(root, text="3. 日志", style="Section.TLabelframe", padding=12)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(18, 0))
        root.rowconfigure(2, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            height=13,
            font=("Menlo", 12),
            wrap=tk.WORD,
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief=tk.FLAT,
            padx=12,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _add_entry(self, parent, row, label, help_text):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=(9, 2))
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky="ew", pady=(9, 2))
        ttk.Label(parent, text=help_text, style="Muted.TLabel").grid(
            row=row + 20,
            column=1,
            sticky="w",
            pady=(0, 4),
        )
        return entry

    def load_config(self):
        try:
            config = self._read_config()
        except Exception as error:
            self._log(f"读取配置失败：{error}")
            self.status_var.set("状态：配置读取失败")
            return

        self._set_entry(self.event_name, config.get("event_name", "周杰伦北京站 2026-06-15 14:00 二开"))
        self._set_entry(self.target_url, config.get("target_url", ""))
        self._set_entry(self.auto_buy_time, config.get("auto_buy_time", "2026-06-15 13:55:00"))
        self._set_entry(self.ticket_num, str(config.get("ticket_num", 1)))
        self._set_entry(self.date, self._format_list(config.get("date", [1])))
        self._set_entry(self.session, self._format_list(config.get("sess", [1])))
        self._set_entry(self.price, self._format_list(config.get("price", [1])))
        self._set_entry(self.viewer_person, self._format_list(config.get("viewer_person", [1])))
        self._set_entry(self.damai_url, config.get("damai_url", "https://www.damai.cn/"))

        self.status_var.set("状态：已加载配置")
        self._log(f"已加载配置：{CONFIG_PATH}")

    def save_config(self):
        try:
            config = self._read_config()
            config.update(
                {
                    "target_url": self.target_url.get().strip(),
                    "event_name": self.event_name.get().strip(),
                    "auto_buy_time": self.auto_buy_time.get().strip(),
                    "ticket_num": self._parse_positive_int(self.ticket_num.get(), "购票数量"),
                    "date": self._parse_int_list(self.date.get(), "日期优先级"),
                    "sess": self._parse_int_list(self.session.get(), "场次优先级"),
                    "price": self._parse_int_list(self.price.get(), "票档优先级"),
                    "viewer_person": self._parse_int_list(self.viewer_person.get(), "观影人序号"),
                    "damai_url": self.damai_url.get().strip() or "https://www.damai.cn/",
                    "driver_path": config.get("driver_path", ""),
                }
            )
            if not config["target_url"]:
                raise ValueError("演出链接不能为空")
            start_time = self._parse_start_time(config["auto_buy_time"])
            sale_time = self._sale_time_hint()
            if sale_time and start_time >= sale_time:
                self._log("提示：启动时间建议早于开抢时间 5-10 分钟，脚本会在开售前持续等待。")
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=4)
        except Exception as error:
            messagebox.showerror("保存失败", str(error))
            self.status_var.set("状态：保存失败")
            self._log(f"保存失败：{error}")
            return False

        self.status_var.set("状态：配置已保存")
        self._log(f"配置已保存：{CONFIG_PATH}")
        return True

    def check_environment(self):
        if not self.save_config():
            return
        self._run_command(self._script_command("--check-env"), "环境检查")

    def start_script(self):
        if self.process and self.process.poll() is None:
            messagebox.showinfo("正在运行", "脚本已经在运行中。")
            return
        if not self.save_config():
            return
        self._run_command(self._script_command(), "真实脚本", keep_running=True)

    def schedule_script(self):
        if self.process and self.process.poll() is None:
            messagebox.showinfo("正在运行", "脚本已经在运行中。")
            return
        if not self.save_config():
            return
        try:
            start_time = self._parse_start_time(self.auto_buy_time.get())
        except ValueError as error:
            messagebox.showerror("定时失败", str(error))
            return

        delay_ms = int((start_time - datetime.now()).total_seconds() * 1000)
        if delay_ms <= 0:
            if not messagebox.askyesno("开抢时间已过", "开抢时间已经过去，要现在立即启动吗？"):
                return
            self.start_script()
            return

        self.cancel_schedule()
        self.schedule_after_id = self.window.after(delay_ms, self._scheduled_start)
        self.schedule_button.config(state=tk.DISABLED)
        self.cancel_schedule_button.config(state=tk.NORMAL)
        self.status_var.set(f"状态：已定时 {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"已定时启动：{start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"距离启动约 {delay_ms // 1000} 秒。请保持此窗口和电脑唤醒。")

    def cancel_schedule(self):
        if self.schedule_after_id is not None:
            self.window.after_cancel(self.schedule_after_id)
            self.schedule_after_id = None
            self._log("已取消定时启动。")
        self.schedule_button.config(state=tk.NORMAL)
        self.cancel_schedule_button.config(state=tk.DISABLED)

    def _scheduled_start(self):
        self.schedule_after_id = None
        self.schedule_button.config(state=tk.NORMAL)
        self.cancel_schedule_button.config(state=tk.DISABLED)
        self._log("到达开抢时间，开始启动真实脚本。")
        self.start_script()

    def login_test(self):
        if not self.save_config():
            return
        self._run_command(self._script_command("--login-only"), "登录测试", keep_running=True)

    def open_target_test(self):
        if not self.save_config():
            return
        self._run_command(
            self._script_command("--open-target-only", "--hold-seconds", "30"),
            "演出页测试",
            keep_running=True,
        )

    def stop_script(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._log("已发送停止信号。")
        self.stop_button.config(state=tk.DISABLED)
        self.start_button.config(state=tk.NORMAL)

    def _run_command(self, command, label, keep_running=False):
        self._log("")
        self._log(f"开始执行：{label}")
        self._log(" ".join(command))
        self.status_var.set(f"状态：{label}运行中")
        self.start_button.config(state=tk.DISABLED if keep_running else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if keep_running else tk.DISABLED)

        thread = threading.Thread(target=self._command_worker, args=(command, label, keep_running), daemon=True)
        thread.start()

    def _script_command(self, *args):
        return [sys.executable, "-u", str(SCRIPT_PATH), *args]

    def _command_worker(self, command, label, keep_running):
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.output_queue.put(("log", line.rstrip()))
            return_code = self.process.wait()
        except Exception as error:
            self.output_queue.put(("error", f"{label}启动失败：{error}"))
            return

        if return_code == 0:
            self.output_queue.put(("done", f"{label}完成。"))
        else:
            self.output_queue.put(("error", f"{label}退出，返回码：{return_code}"))
        if keep_running:
            self.output_queue.put(("script_stopped", ""))

    def _poll_output(self):
        try:
            while True:
                kind, text = self.output_queue.get_nowait()
                if kind == "log":
                    self._log(text)
                elif kind == "done":
                    self.status_var.set(f"状态：{text}")
                    self._log(text)
                elif kind == "error":
                    self.status_var.set(f"状态：{text}")
                    self._log(text)
                elif kind == "script_stopped":
                    self.start_button.config(state=tk.NORMAL)
                    self.stop_button.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.window.after(120, self._poll_output)

    def _read_config(self):
        if not CONFIG_PATH.exists():
            return {
                "event_name": "周杰伦北京站 2026-06-15 14:00 二开",
                "date": [1],
                "sess": [1],
                "price": [1],
                "ticket_num": 1,
                "viewer_person": [1],
                "driver_path": "",
                "damai_url": "https://www.damai.cn/",
                "target_url": "https://m.damai.cn/damai/detail/item.html?itemId=1055320817964",
                "auto_buy_time": "2026-06-15 13:55:00",
            }
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            return json.load(file)

    def _set_entry(self, entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _format_list(self, values):
        if isinstance(values, list):
            return ",".join(str(item) for item in values)
        return str(values)

    def _parse_int_list(self, value, label):
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError(f"{label}不能为空")
        result = []
        for item in items:
            if not item.isdigit() or int(item) <= 0:
                raise ValueError(f"{label}只能填写正整数，用英文逗号分隔")
            result.append(int(item))
        return result

    def _parse_positive_int(self, value, label):
        value = value.strip()
        if not value.isdigit() or int(value) <= 0:
            raise ValueError(f"{label}必须是正整数")
        return int(value)

    def _parse_start_time(self, value):
        value = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        raise ValueError("启动时间格式应为 2026-06-15 13:55:00")

    def _sale_time_hint(self):
        event_name = self.event_name.get()
        if "2026-06-15" not in event_name or "14:00" not in event_name:
            return None
        return datetime(2026, 6, 15, 14, 0, 0)

    def _log(self, message):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)


if __name__ == "__main__":
    app = TicketHelperGUI()
    app.window.mainloop()
