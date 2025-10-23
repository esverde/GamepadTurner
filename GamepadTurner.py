import os
import sys
import threading
import time
import tkinter as tk
from tkinter import font, ttk

import pystray
from PIL import Image
from pygame import event, joystick
from pygame import init as pygame_init
from pygame import quit as pygame_quit
from requests import exceptions, get

# --- 核心修复：在导入pygame前设置虚拟视频驱动 ---
os.environ["SDL_VIDEODRIVER"] = "dummy"

# --- 手柄和翻页逻辑配置 (保持不变) ---
NEXT_PAGE_BUTTONS = {10, 11, 7}
NEXT_PAGE_AXES = {0, 1}
PREV_PAGE_BUTTONS = {5, 8, 9}
PREV_PAGE_AXES = {0, 1}
AXIS_THRESHOLD = 0.8
COOLDOWN_SECONDS = 0.4


# 打包 exe 时注意替换下面语句
# 打包 exe 用
ROOT_PATH = os.path.dirname(sys.executable)

# 代码运行时用
# ROOT_PATH = os.getcwd()
ICON_PATH = os.path.join(ROOT_PATH, "icon.ico")


class PageTurnerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("手柄无线翻页器")
        self.root.iconbitmap(ICON_PATH)
        self.root.geometry("400x280")
        self.root.resizable(False, False)

        self.style = ttk.Style(self.root)
        available_themes = self.style.theme_names()
        if "vista" in available_themes:
            self.style.theme_use("vista")
        elif "clam" in available_themes:
            self.style.theme_use("clam")

        self.is_running = False
        self.joystick_obj = None
        self.last_action_time = 0

        # --- 托盘图标相关属性 ---
        self.tray_icon = None
        self.tray_thread = None

        self.create_widgets()
        self.init_joystick()

        # --- 将默认的最小化(_)按钮行为改为最小化到托盘 ---
        self.root.bind("<Unmap>", self.handle_minimize)

    def create_widgets(self):
        # (此方法内容保持不变)
        main_frame = ttk.Frame(self.root, padding="20 20 20 10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        center_frame = ttk.Frame(main_frame)
        center_frame.pack(expand=True)
        center_frame.columnconfigure(1, weight=1)
        label_font = font.Font(family="Microsoft YaHei", size=10)
        button_font = font.Font(
            family="Microsoft YaHei", size=11, weight="bold"
        )
        self.style.configure("Custom.TLabel", font=label_font)
        self.style.configure("Custom.TEntry", font=label_font)
        self.style.configure("Custom.TButton", font=button_font, padding=5)
        self.style.configure("Status.TLabel", font=label_font, padding="5 2")
        ttk.Label(
            center_frame, text="阅读器 IP 地址:", style="Custom.TLabel"
        ).grid(row=0, column=0, sticky=tk.W, pady=8, padx=5)
        self.ip_var = tk.StringVar(value="192.168.1.10")
        self.ip_entry = ttk.Entry(
            center_frame,
            textvariable=self.ip_var,
            width=20,
            style="Custom.TEntry",
        )
        self.ip_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(center_frame, text="端口:", style="Custom.TLabel").grid(
            row=1, column=0, sticky=tk.W, pady=8, padx=5
        )
        self.port_var = tk.StringVar(value="8080")
        self.port_entry = ttk.Entry(
            center_frame,
            textvariable=self.port_var,
            width=20,
            style="Custom.TEntry",
        )
        self.port_entry.grid(row=1, column=1, sticky=tk.W, padx=5)
        self.toggle_button = ttk.Button(
            center_frame,
            text="启动翻页",
            command=self.toggle_process,
            width=15,
            style="Custom.TButton",
        )
        self.toggle_button.grid(row=2, column=0, columnspan=2, pady=25)
        self.status_var = tk.StringVar(value="正在初始化...")
        status_label = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            style="Status.TLabel",
        )
        status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def init_joystick(self):
        try:
            pygame_init()
            if joystick.get_count() > 0:
                self.joystick_obj = joystick.Joystick(0)
                self.joystick_obj.init()
                self.status_var.set(
                    f"手柄已连接: {self.joystick_obj.get_name()}。准备就绪。"
                )
            else:
                self.status_var.set("错误: 未检测到手柄，请连接后再试。")
                self.toggle_button.config(state=tk.DISABLED)
        except Exception as e:
            self.status_var.set(f"手柄初始化失败: {e}")

    def toggle_process(self):
        if self.is_running:
            self.is_running = False
            self.toggle_button.config(text="启动翻页")
            self.ip_entry.config(state=tk.NORMAL)
            self.port_entry.config(state=tk.NORMAL)
            self.status_var.set("翻页功能已停止。")
        else:
            self.is_running = True
            self.toggle_button.config(text="停止翻页")
            self.ip_entry.config(state=tk.DISABLED)
            self.port_entry.config(state=tk.DISABLED)
            self.status_var.set("翻页功能运行中...")
            self.poll_controller()

    def poll_controller(self):
        if not self.is_running or not self.joystick_obj:
            return
        try:
            event.pump()
            for button_id in NEXT_PAGE_BUTTONS:
                if self.joystick_obj.get_button(button_id):
                    self.turn_page("next")
                    break
            for axis_id in NEXT_PAGE_AXES:
                if self.joystick_obj.get_axis(axis_id) >= AXIS_THRESHOLD:
                    self.turn_page("next")
                    break
            for button_id in PREV_PAGE_BUTTONS:
                if self.joystick_obj.get_button(button_id):
                    self.turn_page("prev")
                    break
            for axis_id in PREV_PAGE_AXES:
                if self.joystick_obj.get_axis(axis_id) <= -AXIS_THRESHOLD:
                    self.turn_page("prev")
                    break
        except Exception:
            self.status_var.set("错误: 手柄连接丢失。请重启应用。")
            self.toggle_button.config(state=tk.DISABLED)
            self.is_running = False
            return

        self.root.after(20, self.poll_controller)

    def turn_page(self, direction):
        current_time = time.time()
        if current_time - self.last_action_time < COOLDOWN_SECONDS:
            return
        ip = self.ip_var.get()
        port = self.port_var.get()
        base_url = f"http://{ip}:{port}/koreader/event/GotoViewRel"
        url = f"{base_url}/1" if direction == "next" else f"{base_url}/-1"
        action_text = "向后翻页" if direction == "next" else "向前翻页"
        try:
            get(url, timeout=1.0)
            self.status_var.set(f"操作成功: {action_text}")
        except exceptions.RequestException:
            self.status_var.set(f"错误: 无法连接到 {ip}:{port}")
        finally:
            self.last_action_time = current_time

    # --- 新增的最小化事件处理方法 ---
    def handle_minimize(self, event):
        """处理窗口最小化事件"""
        # 当窗口状态变为 'iconic' (最小化) 时，触发隐藏到托盘
        # 我们检查 'iconic' 状态以确保这确实是最小化操作，
        # 而不是 'withdraw()' 导致的 <Unmap> 事件。
        # (event 参数是Tkinter事件绑定所必需的)
        if self.root.state() == "iconic":
            self.hide_to_tray()

    # --- 托盘图标及窗口管理方法 ---
    def create_icon_image(self):
        image = Image.open(ICON_PATH)
        return image

    def setup_tray_icon(self):
        # (此方法内容保持不变)
        """设置托盘图标及其菜单"""
        icon_image = self.create_icon_image()
        menu = (
            pystray.MenuItem("显示窗口", self.show_window, default=True),
            pystray.MenuItem("退出", self.quit_application),
        )
        self.tray_icon = pystray.Icon(
            "PageTurner", icon_image, "手柄无线翻页器", menu
        )
        return self.tray_icon

    def show_window(self):
        # (此方法内容保持不变)
        """从托盘恢复窗口 (已修复Bug)"""
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None  # 关键修复

        if self.tray_thread and not self.tray_thread.is_alive():
            self.tray_thread = None

        self.root.after(0, self.root.deiconify)  # 恢复窗口

    def hide_to_tray(self):
        # (此方法内容保持不变)
        """隐藏窗口并显示托盘图标"""
        self.root.withdraw()  # 隐藏主窗口

        if not self.tray_thread or not self.tray_thread.is_alive():
            if not self.tray_icon:
                self.tray_icon = self.setup_tray_icon()

            self.tray_thread = threading.Thread(
                target=self.tray_icon.run, daemon=True
            )
            self.tray_thread.start()

    def quit_application(self):
        # (此方法内容保持不变)
        """完全退出应用程序。"""
        if self.tray_icon:
            self.tray_icon.stop()

        self.is_running = False
        try:
            pygame_quit()
        except Exception as e:
            print(f"关闭Pygame时出错: {e}")

        self.root.destroy()


if __name__ == "__main__":
    main_root = tk.Tk()
    app = PageTurnerApp(main_root)
    main_root.mainloop()
