#!/usr/bin/env python3
"""
Quick Access Menu - Steam Deck styled with touch support
Fixed: Launch menu in separate process with own X11 connection
"""

import tkinter as tk
from tkinter import ttk
import subprocess
import os
import json
import re
import sys
import signal
import time
import logging
import threading
import tempfile
import atexit
from datetime import datetime
from pathlib import Path

# Set up logging
LOG_FILE = Path.home() / '.config' / 'quick_access' / 'debug.log'
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

if LOG_FILE.exists():
    try:
        with open(LOG_FILE, 'w') as f:
            f.write(f"=== Log started at {datetime.now()} ===\n")
    except:
        pass

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(levelname)s: %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

# Font configuration
class Fonts:
    _available_fonts = None

    @classmethod
    def get_available_fonts(cls):
        if cls._available_fonts is None:
            try:
                import tkinter.font as tkfont
                temp_root = tk.Tk()
                cls._available_fonts = set(tkfont.families())
                temp_root.destroy()
            except Exception as e:
                logging.error(f"Error getting fonts: {e}")
                cls._available_fonts = set()
        return cls._available_fonts

    @classmethod
    def get_font(cls, weight, size):
        available = cls.get_available_fonts()

        font_variants = {
            "black": ["Montserrat Black", "Montserrat-Black", "MontserratBlack", "Montserrat"],
            "bold": ["Montserrat Bold", "Montserrat-Bold", "MontserratBold", "Montserrat"],
            "semibold": ["Montserrat SemiBold", "Montserrat-SemiBold", "MontserratSemiBold", "Montserrat Medium", "Montserrat"]
        }

        for font_name in font_variants[weight]:
            if font_name in available:
                if weight == "black" or weight == "bold":
                    tk_weight = "bold"
                else:
                    tk_weight = "normal"
                return (font_name, size, tk_weight)

        if weight == "black" or weight == "bold":
            return ("Arial", size, "bold")
        else:
            return ("Arial", size, "normal")

class AppSuspender:
    """Suspends and resumes applications"""

    def __init__(self):
        self.suspended_pids = []
        self.suspended_name = None
        self.suspended_window_id = None
        logging.info("AppSuspender initialized")

    def get_focused_app_info(self):
        """Get info about the currently focused window"""
        try:
            result = subprocess.run(['xdotool', 'getactivewindow'],
                                   capture_output=True, text=True, timeout=2)
            if not result.stdout:
                return None, None, None

            window_id = result.stdout.strip()

            pid_result = subprocess.run(['xdotool', 'getwindowpid', window_id],
                                      capture_output=True, text=True, timeout=2)
            if not pid_result.stdout:
                return None, None, None

            pid = int(pid_result.stdout.strip())

            try:
                with open(f'/proc/{pid}/comm', 'r') as f:
                    name = f.read().strip()
            except:
                name = "Unknown"

            own_pid = os.getpid()

            skip_processes = ['openbox', 'xbindkeys', 'pegasus', 'bash', 'zsh',
                             'xterm', 'terminal', 'python', 'python3', 'xdotool']

            if name in skip_processes or pid == own_pid:
                logging.debug(f"Skipping process: {name} (PID: {pid})")
                return None, None, None

            return pid, name, window_id

        except Exception as e:
            logging.debug(f"Error getting focused app info: {e}")
            return None, None, None

    def suspend_focused_app(self):
        """Suspend the currently focused application"""
        pid, name, window_id = self.get_focused_app_info()

        if pid and name:
            try:
                os.kill(pid, signal.SIGSTOP)
                self.suspended_pids.append(pid)
                self.suspended_name = name
                self.suspended_window_id = window_id
                logging.info(f"Suspended: {name} (PID: {pid})")

                try:
                    subprocess.run(['playerctl', 'pause'],
                                 stderr=subprocess.DEVNULL, timeout=1)
                except:
                    pass

                return True
            except Exception as e:
                logging.error(f"Error suspending app: {e}")
        else:
            logging.info("No game/application to suspend")

        return False

    def resume_app(self):
        """Resume the suspended application"""
        for pid in self.suspended_pids:
            try:
                os.kill(pid, signal.SIGCONT)
                logging.info(f"Resumed PID {pid}")
            except Exception as e:
                logging.debug(f"Error resuming PID {pid}: {e}")

        self.suspended_pids = []
        self.suspended_name = None
        self.suspended_window_id = None

class PowerModeManager:
    """Manages TDP/Power modes using nvpmodel - non-blocking"""

    def __init__(self):
        self.mode_display = {
            0: "Console",
            1: "Handheld",
            2: "OC CPU",
            3: "OC GPU",
            4: "OC All",
            5: "Perf All",
            6: "Perf OC All",
        }

        self.fan_modes = ["Console", "Handheld", "Cool"]

        self.current_mode_id, self.current_mode_name, self.current_fan = self.get_current_settings()
        logging.info(f"PowerModeManager initialized - Mode: {self.current_mode_name}, Fan: {self.current_fan}")

    def get_current_settings(self):
        """Get current power mode and fan profile using nvpmodel --query"""
        try:
            result = subprocess.run(['nvpmodel', '--query'],
                                   capture_output=True, text=True, timeout=2)
            if result.stdout:
                output = result.stdout.strip()

                current_fan = "Console"
                fan_match = re.search(r'NV Fan Mode:\s*(\w+)', output, re.IGNORECASE)
                if fan_match:
                    current_fan = fan_match.group(1)

                current_mode_name = "Console"
                mode_match = re.search(r'NV Power Mode:\s*(\w+)', output, re.IGNORECASE)
                if mode_match:
                    current_mode_name = mode_match.group(1)

                lines = output.split('\n')
                if lines and lines[-1].strip().isdigit():
                    mode_id = int(lines[-1].strip())
                else:
                    mode_id = 0

                return mode_id, current_mode_name, current_fan

        except Exception as e:
            logging.error(f"Error getting current settings: {e}")

        return 0, "Console", "Console"

    def set_mode_by_id_async(self, mode_id, callback=None):
        """Set power mode in a separate thread"""
        def run():
            try:
                subprocess.run(['sudo', 'nvpmodel', '-m', str(mode_id)],
                               check=True, capture_output=True, timeout=5)
                self.current_mode_id = mode_id
                self.current_mode_name = self.mode_display[mode_id]
                logging.info(f"Set power mode to {mode_id}: {self.current_mode_name}")
                if callback:
                    callback(True, self.current_mode_name)
            except Exception as e:
                logging.error(f"Error setting power mode: {e}")
                if callback:
                    callback(False, None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def set_fan_async(self, fan_mode, callback=None):
        """Set fan profile in a separate thread"""
        def run():
            try:
                subprocess.run(['sudo', 'nvpmodel', '-d', fan_mode],
                               check=True, capture_output=True, timeout=5)
                self.current_fan = fan_mode
                logging.info(f"Set fan profile to {fan_mode}")
                if callback:
                    callback(True, fan_mode)
            except Exception as e:
                logging.error(f"Error setting fan profile: {e}")
                if callback:
                    callback(False, None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

class QuickAccessMenu:
    def __init__(self, root, app_suspender, power_manager):
        self.root = root
        self.app_suspender = app_suspender
        self.power_manager = power_manager
        self.root.title("")
        self._all_widgets = []

        # Set window type
        try:
            self.root.tk.call('wm', 'attributes', '.', '-type', 'utility')
        except:
            pass

        # Remove window decorations
        self.root.overrideredirect(True)

        # Set always on top
        self.root.attributes('-topmost', True)

        # Position window
        self.update_display_dimensions()

        # Setup fonts
        self.setup_fonts()

        # Create UI
        self.setup_styles()

        # Load config
        self.config_file = Path.home() / '.config' / 'quick_access' / 'config.json'
        self.load_config()

        # Create UI
        self.create_main_container()

        # Force window to show
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

        # Force X11 sync
        for _ in range(5):
            self.root.update_idletasks()
            self.root.update()
            time.sleep(0.01)

        logging.info("QuickAccessMenu window ready")

        # Bind keys
        self.root.bind('<Escape>', lambda e: self.quit_menu())
        self.root.protocol("WM_DELETE_WINDOW", self.quit_menu)

        # Signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        logging.info("QuickAccessMenu initialized")

    def setup_fonts(self):
        """Setup fonts"""
        self.font_black = Fonts.get_font("black", 18)
        self.font_bold = Fonts.get_font("bold", 14)
        self.font_semibold = Fonts.get_font("semibold", 12)
        self.font_bold_small = Fonts.get_font("bold", 12)
        self.font_large = Fonts.get_font("bold", 36)
        self.font_medium = Fonts.get_font("bold", 24)

    def signal_handler(self, signum, frame):
        logging.info(f"Received signal {signum}")
        self.quit_menu()

    def quit_menu(self):
        logging.info("Quitting menu...")
        self.save_config()
        self.app_suspender.resume_app()
        self.root.quit()

    def kill_game_and_quit(self):
        logging.info("Killing game and quitting...")
        self.save_config()
        if self.app_suspender.suspended_pids:
            for pid in self.app_suspender.suspended_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
        self.root.quit()

    def update_display_dimensions(self):
        self.root.update_idletasks()
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.window_width = 700
        self.window_height = self.screen_height
        x = self.screen_width - self.window_width
        y = 0
        self.root.geometry(f'{self.window_width}x{self.window_height}+{x}+{y}')

    def setup_styles(self):
        self.root.configure(bg=self.colors['bg'])
        style = ttk.Style()

        style.configure('Card.TLabelframe',
                       background=self.colors['card_bg'],
                       foreground=self.colors['fg'],
                       relief='flat', borderwidth=2)
        style.configure('Card.TLabelframe.Label',
                       font=self.font_bold,
                       background=self.colors['card_bg'],
                       foreground=self.colors['accent'])

    @property
    def colors(self):
        return {
            'bg': '#1a1a1a', 'fg': '#ffffff', 'accent': '#1e9e5e',
            'card_bg': '#2a2a2a', 'slider_bg': '#404040',
            'border': '#3a3a3a', 'header_bg': '#252525',
            'button_bg': '#333333', 'button_hover': '#404040',
            'close_btn': '#c44c4c', 'close_btn_hover': '#d45c5c',
            'scrollbar': '#404040', 'scrollbar_active': '#1e9e5e',
            'highlight': '#1e9e5e', 'warning': '#f39c12', 'danger': '#e74c3c'
        }

    def create_main_container(self):
        self.main_frame = tk.Frame(self.root, bg=self.colors['border'], bd=0)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.inner_frame = tk.Frame(self.main_frame, bg=self.colors['bg'], bd=0)
        self.inner_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.create_content_area()
        self.create_sidebar()
        self.root.update_idletasks()

    def create_sidebar(self):
        sidebar = tk.Frame(self.inner_frame, bg=self.colors['card_bg'], width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=0, pady=0)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="QUICK ACCESS",
                font=self.font_black,
                bg=self.colors['card_bg'], fg=self.colors['accent']).pack(pady=(15, 10))

        tk.Frame(sidebar, bg=self.colors['border'], height=2).pack(fill=tk.X, padx=15, pady=5)

        categories = [
            ("system", "SYSTEM", self.colors['button_bg']),
            ("tdp", "TDP & FAN", self.colors['button_bg']),
            ("scripts", "SCRIPTS", self.colors['button_bg']),
            ("power", "POWER", self.colors['button_bg']),
        ]

        self.category_buttons = {}
        for cat_id, name, color in categories:
            btn = tk.Button(sidebar, text=name,
                           font=self.font_bold,
                           bg=color, fg=self.colors['fg'],
                           bd=0, padx=15, pady=10, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda c=cat_id: self.switch_category(c))
            btn.pack(fill=tk.X, padx=15, pady=3)
            self.category_buttons[cat_id] = btn
            self._all_widgets.append(btn)

        self.switch_category("system")

        tk.Frame(sidebar, bg=self.colors['card_bg'], height=20).pack()
        tk.Frame(sidebar, bg=self.colors['border'], height=2).pack(fill=tk.X, padx=15, pady=5)

        game_frame = tk.Frame(sidebar, bg=self.colors['card_bg'])
        game_frame.pack(fill=tk.X, padx=15, pady=10, side=tk.BOTTOM)

        tk.Label(game_frame, text="CURRENT GAME",
                font=self.font_bold_small,
                bg=self.colors['card_bg'], fg=self.colors['accent']).pack(anchor='w')

        game_name = self.app_suspender.suspended_name if self.app_suspender.suspended_name else "None"
        self.game_name_label = tk.Label(game_frame, text=game_name,
                                        font=self.font_semibold,
                                        bg=self.colors['card_bg'], fg=self.colors['fg'],
                                        wraplength=170)
        self.game_name_label.pack(anchor='w', pady=2)

        pid_text = str(self.app_suspender.suspended_pids[0]) if self.app_suspender.suspended_pids else "None"
        tk.Label(game_frame, text=f"PID: {pid_text}",
                font=self.font_semibold,
                bg=self.colors['card_bg'], fg=self.colors['fg']).pack(anchor='w')

        status_text = "SUSPENDED" if self.app_suspender.suspended_pids else "ACTIVE"
        status_color = self.colors['warning'] if self.app_suspender.suspended_pids else self.colors['fg']
        tk.Label(game_frame, text=f"STATUS: {status_text}",
                font=self.font_bold_small,
                bg=self.colors['card_bg'], fg=status_color).pack(anchor='w', pady=(2, 5))

        btn_frame = tk.Frame(game_frame, bg=self.colors['card_bg'])
        btn_frame.pack(fill=tk.X, pady=5)

        resume_text = "RESUME" if self.app_suspender.suspended_pids else "CLOSE"
        resume_btn = tk.Button(btn_frame, text=resume_text,
                               font=self.font_bold_small,
                               bg=self.colors['button_bg'], fg=self.colors['fg'],
                               bd=0, padx=10, pady=6, cursor='hand2',
                               activebackground=self.colors['button_hover'],
                               command=self.quit_menu)
        resume_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        if self.app_suspender.suspended_pids:
            kill_btn = tk.Button(btn_frame, text="KILL",
                                 font=self.font_bold_small,
                                 bg=self.colors['danger'], fg='white',
                                 bd=0, padx=10, pady=6, cursor='hand2',
                                 activebackground='#c0392b',
                                 command=self.kill_game_and_quit)
            kill_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        self._all_widgets.append(resume_btn)

    def create_content_area(self):
        self.content_area = tk.Frame(self.inner_frame, bg=self.colors['bg'])
        self.content_area.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.content_canvas = tk.Canvas(self.content_area, bg=self.colors['bg'], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(self.content_area, orient=tk.VERTICAL, command=self.content_canvas.yview,
                                 bg=self.colors['scrollbar'], activebackground=self.colors['scrollbar_active'],
                                 troughcolor=self.colors['bg'], width=20, bd=0)

        self.content_scrollable = tk.Frame(self.content_canvas, bg=self.colors['bg'])

        self.content_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.content_canvas_frame = self.content_canvas.create_window((0, 0), window=self.content_scrollable, anchor='nw')

        self.content_scrollable.bind('<Configure>', self.on_content_configure)
        self.content_canvas.bind('<Configure>', self.on_content_canvas_configure)
        self.content_canvas.bind('<Enter>', self._bind_content_mousewheel)
        self.content_canvas.bind('<Leave>', self._unbind_content_mousewheel)

    def switch_category(self, category_id):
        self.current_category = category_id

        if hasattr(self, 'category_buttons'):
            for cat_id, btn in self.category_buttons.items():
                if cat_id == category_id:
                    btn.config(bg=self.colors['accent'], fg='#000000')
                else:
                    btn.config(bg=self.colors['button_bg'], fg=self.colors['fg'])

        for widget in self.content_scrollable.winfo_children():
            widget.destroy()

        if category_id == "system":
            self.create_system_content()
        elif category_id == "tdp":
            self.create_tdp_content()
        elif category_id == "scripts":
            self.create_scripts_content()
        elif category_id == "power":
            self.create_power_content()

        self.root.update_idletasks()

    def create_system_content(self):
        title = tk.Label(self.content_scrollable, text="SYSTEM CONTROLS",
                        font=self.font_black,
                        bg=self.colors['bg'], fg=self.colors['accent'])
        title.pack(pady=(0, 20))

        # Brightness card
        brightness_card = tk.Frame(self.content_scrollable, bg=self.colors['card_bg'])
        brightness_card.pack(fill=tk.X, pady=10, padx=10)

        tk.Label(brightness_card, text="BRIGHTNESS",
                font=self.font_bold,
                bg=self.colors['card_bg'], fg=self.colors['accent']).pack(anchor='w', padx=20, pady=(20, 10))

        brightness = self.get_brightness()

        self.bright_label = tk.Label(brightness_card, text=f"{brightness}%",
                                     font=self.font_large,
                                     bg=self.colors['card_bg'], fg=self.colors['accent'])
        self.bright_label.pack(pady=5)

        self.bright_slider = self.create_slider(brightness_card, 1, 100, brightness, self.set_brightness)

        preset_frame = tk.Frame(brightness_card, bg=self.colors['card_bg'])
        preset_frame.pack(fill=tk.X, pady=15, padx=20)

        for label, level in [("Night", 20), ("Indoor", 60), ("Full", 100)]:
            btn = tk.Button(preset_frame, text=label,
                           font=self.font_semibold,
                           bg=self.colors['button_bg'], fg=self.colors['fg'],
                           bd=0, padx=15, pady=8, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda l=level: self.set_brightness(l))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
            self._all_widgets.append(btn)

        # Volume card
        volume_card = tk.Frame(self.content_scrollable, bg=self.colors['card_bg'])
        volume_card.pack(fill=tk.X, pady=10, padx=10)

        tk.Label(volume_card, text="VOLUME",
                font=self.font_bold,
                bg=self.colors['card_bg'], fg=self.colors['accent']).pack(anchor='w', padx=20, pady=(20, 10))

        volume = self.get_volume()

        self.vol_label = tk.Label(volume_card, text=f"{int(volume)}%",
                                  font=self.font_large,
                                  bg=self.colors['card_bg'], fg=self.colors['accent'])
        self.vol_label.pack(pady=5)

        self.vol_slider = self.create_slider(volume_card, 0, 100, volume, self.set_volume)

        control_frame = tk.Frame(volume_card, bg=self.colors['card_bg'])
        control_frame.pack(fill=tk.X, pady=15, padx=20)

        self.mute_btn = tk.Button(control_frame, text="MUTE",
                                  font=self.font_bold_small,
                                  bg=self.colors['button_bg'], fg=self.colors['fg'],
                                  bd=0, padx=15, pady=8, cursor='hand2',
                                  activebackground=self.colors['button_hover'],
                                  command=self.toggle_mute)
        self.mute_btn.pack(side=tk.LEFT, padx=3)
        self._all_widgets.append(self.mute_btn)

        for level, label in [(50, "50%"), (100, "100%")]:
            btn = tk.Button(control_frame, text=label,
                           font=self.font_semibold,
                           bg=self.colors['button_bg'], fg=self.colors['fg'],
                           bd=0, padx=15, pady=8, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda l=level: self.set_volume(l))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
            self._all_widgets.append(btn)

        tk.Frame(self.content_scrollable, bg=self.colors['bg'], height=20).pack()

    def create_tdp_content(self):
        title = tk.Label(self.content_scrollable, text="TDP & FAN CONTROL",
                        font=self.font_black,
                        bg=self.colors['bg'], fg=self.colors['accent'])
        title.pack(pady=(0, 20))

        # TDP card
        tdp_card = tk.Frame(self.content_scrollable, bg=self.colors['card_bg'])
        tdp_card.pack(fill=tk.X, pady=10, padx=10)

        tk.Label(tdp_card, text="TDP MODE",
                font=self.font_bold,
                bg=self.colors['card_bg'], fg=self.colors['accent']).pack(anchor='w', padx=20, pady=(20, 10))

        current_name = self.power_manager.current_mode_name
        self.current_tdp_label = tk.Label(tdp_card, text=current_name,
                                          font=self.font_medium,
                                          bg=self.colors['card_bg'], fg=self.colors['accent'])
        self.current_tdp_label.pack(pady=5)

        tdp_modes = [
            (0, "Console"), (1, "Handheld"), (2, "OC CPU"),
            (3, "OC GPU"), (4, "OC All"), (5, "Perf All"), (6, "Perf OC All"),
        ]

        row1 = tk.Frame(tdp_card, bg=self.colors['card_bg'])
        row1.pack(fill=tk.X, pady=10, padx=20)

        for mode_id, name in tdp_modes[:4]:
            btn = tk.Button(row1, text=name,
                           font=self.font_semibold,
                           bg=self.colors['button_bg'], fg=self.colors['fg'],
                           bd=0, padx=10, pady=6, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda m=mode_id, n=name: self.set_tdp_mode_async(m, n))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
            self._all_widgets.append(btn)

        row2 = tk.Frame(tdp_card, bg=self.colors['card_bg'])
        row2.pack(fill=tk.X, pady=5, padx=20)

        for mode_id, name in tdp_modes[4:]:
            btn = tk.Button(row2, text=name,
                           font=self.font_semibold,
                           bg=self.colors['button_bg'], fg=self.colors['fg'],
                           bd=0, padx=10, pady=6, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda m=mode_id, n=name: self.set_tdp_mode_async(m, n))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
            self._all_widgets.append(btn)

        # Fan card
        fan_card = tk.Frame(self.content_scrollable, bg=self.colors['card_bg'])
        fan_card.pack(fill=tk.X, pady=10, padx=10)

        tk.Label(fan_card, text="FAN MODE",
                font=self.font_bold,
                bg=self.colors['card_bg'], fg=self.colors['accent']).pack(anchor='w', padx=20, pady=(20, 10))

        current_fan = self.power_manager.current_fan
        self.current_fan_label = tk.Label(fan_card, text=current_fan,
                                          font=self.font_medium,
                                          bg=self.colors['card_bg'], fg=self.colors['accent'])
        self.current_fan_label.pack(pady=5)

        fan_row = tk.Frame(fan_card, bg=self.colors['card_bg'])
        fan_row.pack(fill=tk.X, pady=15, padx=20)

        for fan_mode in ["Console", "Handheld", "Cool"]:
            btn = tk.Button(fan_row, text=fan_mode,
                           font=self.font_semibold,
                           bg=self.colors['button_bg'], fg=self.colors['fg'],
                           bd=0, padx=10, pady=6, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda f=fan_mode: self.set_fan_mode_async(f))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
            self._all_widgets.append(btn)

        tk.Frame(self.content_scrollable, bg=self.colors['bg'], height=20).pack()

    def set_tdp_mode_async(self, mode_id, name):
        def callback(success, new_name):
            if success:
                self.current_tdp_label.config(text=name)
                try:
                    subprocess.run(['notify-send', 'TDP', f'Switched to {name}',
                                  '-t', '2000'], stderr=subprocess.DEVNULL)
                except:
                    pass
        self.power_manager.set_mode_by_id_async(mode_id, callback)

    def set_fan_mode_async(self, fan_mode):
        def callback(success, new_mode):
            if success:
                self.current_fan_label.config(text=fan_mode)
                try:
                    subprocess.run(['notify-send', 'Fan', f'Switched to {fan_mode} fan',
                                  '-t', '2000'], stderr=subprocess.DEVNULL)
                except:
                    pass
        self.power_manager.set_fan_async(fan_mode, callback)

    def create_scripts_content(self):
        title = tk.Label(self.content_scrollable, text="SCRIPTS",
                        font=self.font_black,
                        bg=self.colors['bg'], fg=self.colors['accent'])
        title.pack(pady=(0, 20))

        scripts_card = tk.Frame(self.content_scrollable, bg=self.colors['card_bg'])
        scripts_card.pack(fill=tk.X, pady=10, padx=10)

        scripts = [
            ("Lock Screen", "loginctl lock-session"),
            ("Screenshot", "gnome-screenshot -i"),
            ("Night Light", "redshift -O 3500"),
            ("Reset Night Light", "redshift -x"),
        ]

        for name, cmd in scripts:
            btn = tk.Button(scripts_card, text=name,
                           font=self.font_semibold,
                           bg=self.colors['button_bg'], fg=self.colors['fg'],
                           bd=0, padx=20, pady=12, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda c=cmd: self.run_command(c))
            btn.pack(fill=tk.X, pady=5, padx=20)
            self._all_widgets.append(btn)

        tk.Frame(self.content_scrollable, bg=self.colors['bg'], height=20).pack()

    def create_power_content(self):
        title = tk.Label(self.content_scrollable, text="POWER",
                        font=self.font_black,
                        bg=self.colors['bg'], fg=self.colors['accent'])
        title.pack(pady=(0, 20))

        power_card = tk.Frame(self.content_scrollable, bg=self.colors['card_bg'])
        power_card.pack(fill=tk.X, pady=10, padx=10)

        power_options = [
            ("Suspend", "systemctl suspend", self.colors['button_bg']),
            ("Restart", "systemctl reboot", self.colors['close_btn']),
            ("Shutdown", "systemctl poweroff", self.colors['close_btn']),
        ]

        for name, cmd, color in power_options:
            btn = tk.Button(power_card, text=name,
                           font=self.font_semibold,
                           bg=color, fg=self.colors['fg'],
                           bd=0, padx=20, pady=12, cursor='hand2',
                           activebackground=self.colors['button_hover'],
                           command=lambda c=cmd: self.run_command(c))
            btn.pack(fill=tk.X, pady=5, padx=20)
            self._all_widgets.append(btn)

        tk.Frame(self.content_scrollable, bg=self.colors['bg'], height=20).pack()

    def create_slider(self, parent, from_, to, value, command):
        frame = tk.Frame(parent, bg=self.colors['card_bg'])
        frame.pack(fill=tk.X, pady=10, padx=20)

        slider = tk.Scale(frame, from_=from_, to=to, orient=tk.HORIZONTAL,
                         length=450, width=35, sliderlength=50, showvalue=False,
                         bg=self.colors['card_bg'], fg=self.colors['fg'],
                         troughcolor=self.colors['slider_bg'],
                         activebackground=self.colors['accent'],
                         highlightbackground=self.colors['border'],
                         highlightthickness=0, bd=0,
                         command=command)
        slider.set(value)
        slider.pack(fill=tk.X)
        self._all_widgets.append(slider)
        return slider

    def get_brightness(self):
        try:
            result = subprocess.run(['brightnessctl', 'get'], capture_output=True, text=True, timeout=2)
            if result.stdout:
                current = int(result.stdout.strip())
                max_result = subprocess.run(['brightnessctl', 'max'], capture_output=True, text=True, timeout=2)
                if max_result.stdout:
                    max_val = int(max_result.stdout.strip())
                    return int((current / max_val) * 100)
        except:
            pass
        return self.config.get('brightness', 100)

    def set_brightness(self, value):
        try:
            value = int(value)
            value = max(1, min(100, value))
            subprocess.run(['brightnessctl', 'set', f'{value}%'], check=True, capture_output=True, timeout=2)
            self.bright_slider.set(value)
            self.bright_label.config(text=f"{value}%")
            self.config['brightness'] = value
        except:
            pass

    def get_volume(self):
        try:
            result = subprocess.run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'],
                                   capture_output=True, text=True, timeout=2)
            if '%' in result.stdout:
                match = re.search(r'(\d+)%', result.stdout)
                if match:
                    return float(match.group(1))
        except:
            pass
        return self.config.get('volume', 50)

    def set_volume(self, value):
        try:
            value = int(value)
            self.vol_slider.set(value)
            self.vol_label.config(text=f"{value}%")
            subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{value}%'],
                         check=True, capture_output=True, timeout=2)
            self.config['volume'] = value
            if value == 0:
                self.mute_btn.config(text="UNMUTE")
            else:
                self.mute_btn.config(text="MUTE")
        except:
            pass

    def toggle_mute(self):
        try:
            check = subprocess.run(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'],
                                 capture_output=True, text=True, timeout=2)
            subprocess.run(['pactl', 'set-sink-mute', '@DEFAULT_SINK@', 'toggle'],
                         check=True, capture_output=True, timeout=2)
            if 'yes' in check.stdout.lower():
                self.mute_btn.config(text="MUTE")
            else:
                self.mute_btn.config(text="UNMUTE")
        except:
            pass

    def run_command(self, command):
        try:
            logging.info(f"Running: {command}")
            subprocess.Popen(command, shell=True)
        except:
            pass

    def on_content_configure(self, event):
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox('all'))

    def on_content_canvas_configure(self, event):
        self.content_canvas.itemconfig(self.content_canvas_frame, width=event.width)

    def _bind_content_mousewheel(self, event):
        self.content_canvas.bind_all('<MouseWheel>', self._on_content_mousewheel)

    def _unbind_content_mousewheel(self, event):
        self.content_canvas.unbind_all('<MouseWheel>')

    def _on_content_mousewheel(self, event):
        self.content_canvas.yview_scroll(int(-1*(event.delta/120)), 'units')

    @property
    def all_widgets(self):
        return self._all_widgets

    def load_config(self):
        self.config = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            except:
                pass

    def save_config(self):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except:
            pass

def main():
    logging.info("=" * 50)
    logging.info("Quick Access Menu starting up")

    script_name = os.path.basename(__file__)

    # Check for existing instance and kill it (toggle behavior)
    try:
        result = subprocess.run(['pgrep', '-f', script_name], capture_output=True, text=True, timeout=2)
        if result.stdout:
            pids = result.stdout.strip().split('\n')
            current_pid = str(os.getpid())
            other_pids = [pid for pid in pids if pid != current_pid]

            if other_pids:
                logging.info(f"Found existing instance: {other_pids[0]}, killing it...")
                os.kill(int(other_pids[0]), signal.SIGTERM)
                time.sleep(0.2)
                logging.info("Existing instance killed. Exiting.")
                sys.exit(0)
    except Exception as e:
        logging.error(f"Error checking instances: {e}")

    logging.info("No existing instance found, launching...")

    # Create app suspender
    suspender = AppSuspender()

    # Create power mode manager
    power_manager = PowerModeManager()

    # Launch the menu
    root = tk.Tk()
    app = QuickAccessMenu(root, suspender, power_manager)

    # Don't suspend the game until AFTER the menu is fully created and shown
    # This is the key: create the window, THEN suspend the game
    time.sleep(0.1)  # Small delay for window to fully initialize
    suspended = app.app_suspender.suspend_focused_app()

    if suspended:
        logging.info("Game suspended after window creation")
        # Force window to front again after suspension
        root.lift()
        root.focus_force()
        root.attributes('-topmost', True)

    try:
        root.mainloop()
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        suspender.resume_app()
        logging.info("Quick Access Menu closed")

    logging.info("=" * 50)

if __name__ == "__main__":
    main()
