#!/usr/bin/env python3
"""
Quick Access Menu - Steam Deck styled with touch support
Fixed: Suspends focused application while menu is open
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
from datetime import datetime
from pathlib import Path

# Set up logging
LOG_FILE = Path.home() / '.config' / 'quick_access' / 'debug.log'
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

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

class AppSuspender:
    """Suspends and resumes applications"""
    
    def __init__(self):
        self.suspended_pids = []
        self.focused_app_pid = None
        logging.info("AppSuspender initialized")
    
    def get_focused_app_pid(self):
        """Get the PID of the currently focused window"""
        try:
            # Get active window ID using xdotool
            result = subprocess.run(['xdotool', 'getactivewindow'], 
                                   capture_output=True, text=True)
            if result.stdout:
                window_id = result.stdout.strip()
                
                # Get the PID of that window
                pid_result = subprocess.run(['xdotool', 'getwindowpid', window_id],
                                          capture_output=True, text=True)
                if pid_result.stdout:
                    pid = int(pid_result.stdout.strip())
                    logging.debug(f"Focused app PID: {pid}")
                    return pid
        except Exception as e:
            logging.debug(f"Error getting focused app: {e}")
        return None
    
    def suspend_focused_app(self):
        """Suspend the currently focused application"""
        self.focused_app_pid = self.get_focused_app_pid()
        
        if self.focused_app_pid:
            try:
                # Check if it's a game/application we want to suspend
                # (skip system processes like window managers)
                with open(f'/proc/{self.focused_app_pid}/comm', 'r') as f:
                    process_name = f.read().strip()
                
                # Skip certain processes that shouldn't be suspended
                skip_processes = ['openbox', 'xbindkeys', 'pegasus', 'bash', 'zsh', 
                                 'xterm', 'terminal', 'python', 'python3']
                
                if process_name in skip_processes:
                    logging.debug(f"Skipping suspension of {process_name}")
                    return
                
                # Suspend the process
                os.kill(self.focused_app_pid, signal.SIGSTOP)
                self.suspended_pids.append(self.focused_app_pid)
                logging.info(f"Suspended focused app: {process_name} (PID: {self.focused_app_pid})")
                
                # Also try to pause audio if possible
                self.pause_audio()
                
            except Exception as e:
                logging.error(f"Error suspending app: {e}")
    
    def pause_audio(self):
        """Try to pause audio playback"""
        try:
            # Try to pause using playerctl (for media players)
            subprocess.run(['playerctl', 'pause'], 
                         stderr=subprocess.DEVNULL, timeout=1)
            logging.debug("Paused media playback")
        except:
            pass
        
        try:
            # Also try to mute PulseAudio applications from this PID
            if self.focused_app_pid:
                # Get all sink inputs for this PID
                result = subprocess.run(['pactl', 'list', 'sink-inputs'], 
                                      capture_output=True, text=True)
                # Parse output to find sink inputs owned by our PID
                current_sink = None
                for line in result.stdout.split('\n'):
                    if 'Sink Input' in line:
                        current_sink = line
                    elif 'application.process.id' in line and str(self.focused_app_pid) in line:
                        if current_sink:
                            sink_id = re.search(r'#(\d+)', current_sink)
                            if sink_id:
                                # Mute this sink input
                                subprocess.run(['pactl', 'set-sink-input-mute', sink_id.group(1), '1'],
                                             stderr=subprocess.DEVNULL)
                                logging.debug(f"Muted audio for PID {self.focused_app_pid}")
        except Exception as e:
            logging.debug(f"Error pausing audio: {e}")
    
    def resume_app(self):
        """Resume the suspended application"""
        for pid in self.suspended_pids:
            try:
                os.kill(pid, signal.SIGCONT)
                logging.info(f"Resumed PID {pid}")
            except Exception as e:
                logging.debug(f"Error resuming PID {pid}: {e}")
        self.suspended_pids = []
        self.focused_app_pid = None
        
        # Try to resume audio
        self.resume_audio()
    
    def resume_audio(self):
        """Try to resume audio playback"""
        try:
            # Try to play using playerctl
            subprocess.run(['playerctl', 'play'], 
                         stderr=subprocess.DEVNULL, timeout=1)
            logging.debug("Resumed media playback")
        except:
            pass

class QuickAccessMenu:
    def __init__(self, root, app_suspender):
        self.root = root
        self.app_suspender = app_suspender
        self.root.title("")
        
        # Set up signal handlers for clean termination
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # Set window type for better compatibility
        try:
            self.root.tk.call('wm', 'attributes', '.', '-type', 'utility')
            logging.debug("Set window type to utility")
        except Exception as e:
            logging.debug(f"Could not set window type: {e}")
            
        # Remove window decorations
        self.root.overrideredirect(True)
        
        # Set always on top
        self.root.attributes('-topmost', True)
        
        # Get display dimensions
        self.update_display_dimensions()
        
        # Colors - Steam Deck dark theme
        self.colors = {
            'bg': '#1a1a1a', 'fg': '#ffffff', 'accent': '#1e9e5e',
            'accent_hover': '#2eae6e', 'card_bg': '#2a2a2a',
            'card_bg_alt': '#333333', 'slider_bg': '#404040',
            'slider_fg': '#1e9e5e', 'border': '#3a3a3a',
            'header_bg': '#252525', 'button_bg': '#333333',
            'button_hover': '#404040', 'close_btn': '#c44c4c',
            'close_btn_hover': '#d45c5c', 'scrollbar': '#404040',
            'scrollbar_active': '#1e9e5e', 'highlight': '#1e9e5e'
        }
        
        # Navigation variables
        self.all_widgets = []
        self.widget_types = []
        self.current_focus_index = 0
        self.focused_widget = None
        
        # Drag variables
        self.x = None
        self.y = None
        
        # Configure styles
        self.setup_styles()
        
        # Load configuration
        self.config_file = Path.home() / '.config' / 'quick_access' / 'config.json'
        self.load_config()
        
        # Create UI
        self.create_main_container()
        self.create_scrollable_content()
        self.create_all_controls()
        
        # Bind keyboard shortcuts
        self.root.bind('<Escape>', lambda e: self.cleanup_and_quit())
        self.root.bind('<Tab>', self.keyboard_navigate)
        self.root.bind('<Up>', lambda e: self.navigate_up())
        self.root.bind('<Down>', lambda e: self.navigate_down())
        self.root.bind('<Left>', lambda e: self.navigate_left())
        self.root.bind('<Right>', lambda e: self.navigate_right())
        
        # Auto-save config on close
        self.root.protocol("WM_DELETE_WINDOW", self.cleanup_and_quit)
        
        # Force window to top after creation
        self.root.after(50, self.force_window_to_top)
        self.root.after(200, self.force_window_to_top)
        
        logging.info("QuickAccessMenu initialization complete")
        
        # Show a status message about suspended app
        if self.app_suspender.suspended_pids:
            self.show_suspended_notification()
    
    def show_suspended_notification(self):
        """Show a notification that the game/app was suspended"""
        try:
            subprocess.run(['notify-send', 
                          'Quick Access', 
                          f'Game suspended while menu is open',
                          '-t', '2000'],
                         stderr=subprocess.DEVNULL)
        except:
            pass
    
    def signal_handler(self, signum, frame):
        """Handle termination signals"""
        logging.info(f"Received signal {signum}, cleaning up...")
        self.cleanup_and_quit()
    
    def cleanup_and_quit(self):
        """Clean up resources and quit"""
        logging.info("Cleaning up and quitting...")
        self.save_config()
        # Resume the suspended app before quitting
        if hasattr(self, 'app_suspender'):
            self.app_suspender.resume_app()
        logging.info("Exiting application")
        self.root.quit()
    
    def force_window_to_top(self):
        """Simple window forcing"""
        try:
            self.root.lift()
            self.root.focus_force()
            self.root.attributes('-topmost', True)
            logging.debug("Forced window to top via tkinter")
        except Exception as e:
            logging.error(f"Error forcing window to top: {e}")
    
    def update_display_dimensions(self):
        """Update display dimensions and position window"""
        self.root.update_idletasks()
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.window_width = 550
        self.window_height = self.screen_height
        x = self.screen_width - self.window_width
        y = 0
        self.root.geometry(f'{self.window_width}x{self.window_height}+{x}+{y}')
        logging.debug(f"Window dimensions: {self.window_width}x{self.window_height} at +{x}+{y}")
    
    def setup_styles(self):
        """Configure modern dark theme styles"""
        style = ttk.Style()
        self.root.configure(bg=self.colors['bg'])
        
        style.configure('Card.TLabelframe',
                       background=self.colors['card_bg'],
                       foreground=self.colors['fg'],
                       relief='flat',
                       borderwidth=2)
        style.configure('Card.TLabelframe.Label',
                       font=('Arial', 16, 'bold'),
                       background=self.colors['card_bg'],
                       foreground=self.colors['accent'])
    
    def create_main_container(self):
        """Create the main window container"""
        self.main_frame = tk.Frame(self.root, bg=self.colors['border'], bd=0)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        self.inner_frame = tk.Frame(self.main_frame, bg=self.colors['bg'], bd=0)
        self.inner_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        self.create_header()
    
    def create_header(self):
        """Create modern header"""
        header_frame = tk.Frame(self.inner_frame, bg=self.colors['header_bg'], height=60)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)
        
        header_frame.bind('<Button-1>', self.start_move)
        header_frame.bind('<ButtonRelease-1>', self.stop_move)
        header_frame.bind('<B1-Motion>', self.do_move)
        
        left_frame = tk.Frame(header_frame, bg=self.colors['header_bg'])
        left_frame.pack(side=tk.LEFT, padx=15, pady=12)
        left_frame.bind('<Button-1>', self.start_move)
        left_frame.bind('<ButtonRelease-1>', self.stop_move)
        left_frame.bind('<B1-Motion>', self.do_move)
        
        icon_label = tk.Label(left_frame, text="🎮", font=('Arial', 22),
                            bg=self.colors['header_bg'], fg=self.colors['accent'])
        icon_label.pack(side=tk.LEFT, padx=(0, 8))
        icon_label.bind('<Button-1>', self.start_move)
        icon_label.bind('<ButtonRelease-1>', self.stop_move)
        icon_label.bind('<B1-Motion>', self.do_move)
        
        title = tk.Label(left_frame, text="Quick Access", font=('Arial', 18, 'bold'),
                        bg=self.colors['header_bg'], fg=self.colors['fg'])
        title.pack(side=tk.LEFT)
        title.bind('<Button-1>', self.start_move)
        title.bind('<ButtonRelease-1>', self.stop_move)
        title.bind('<B1-Motion>', self.do_move)
        
        close_frame = tk.Frame(header_frame, bg=self.colors['header_bg'])
        close_frame.pack(side=tk.RIGHT, padx=15, pady=12)
        close_frame.bind('<Button-1>', lambda e: 'break')
        close_frame.bind('<B1-Motion>', lambda e: 'break')
        
        close_btn = tk.Button(close_frame, text="✕", font=('Arial', 18, 'bold'),
                            bg=self.colors['close_btn'], fg=self.colors['fg'],
                            bd=0, width=2, height=1, cursor='hand2',
                            activebackground=self.colors['close_btn_hover'],
                            activeforeground=self.colors['fg'],
                            command=self.cleanup_and_quit, relief='flat')
        close_btn.pack()
        close_btn.bind('<Button-1>', lambda e: self.close_button_click(e))
        close_btn.bind('<B1-Motion>', lambda e: 'break')
    
    def close_button_click(self, event):
        self.cleanup_and_quit()
        return 'break'
    
    def start_move(self, event):
        self.x = event.x
        self.y = event.y
    
    def stop_move(self, event):
        self.x = None
        self.y = None
    
    def do_move(self, event):
        if self.x is not None and self.y is not None:
            deltax = event.x - self.x
            deltay = event.y - self.y
            x = self.root.winfo_x() + deltax
            y = self.root.winfo_y() + deltay
            self.root.geometry(f"+{x}+{y}")
    
    def create_scrollable_content(self):
        """Create scrollable content area"""
        self.content_frame = tk.Frame(self.inner_frame, bg=self.colors['bg'])
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        self.canvas = tk.Canvas(self.content_frame, bg=self.colors['bg'],
                               highlightthickness=0, bd=0)
        
        self.scrollbar = tk.Scrollbar(self.content_frame, orient=tk.VERTICAL,
                                     command=self.canvas.yview,
                                     bg=self.colors['scrollbar'],
                                     activebackground=self.colors['scrollbar_active'],
                                     troughcolor=self.colors['bg'],
                                     width=20, bd=0)
        
        self.scrollable_frame = tk.Frame(self.canvas, bg=self.colors['bg'])
        
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas_frame = self.canvas.create_window((0, 0),
                                                      window=self.scrollable_frame,
                                                      anchor='nw',
                                                      width=self.canvas.winfo_width())
        
        self.scrollable_frame.bind('<Configure>', self.on_frame_configure)
        self.canvas.bind('<Configure>', self.on_canvas_configure)
        self.canvas.bind('<Enter>', self._bind_mousewheel)
        self.canvas.bind('<Leave>', self._unbind_mousewheel)
    
    def _bind_mousewheel(self, event):
        self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)
    
    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all('<MouseWheel>')
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), 'units')
    
    def on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    
    def on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_frame, width=event.width)
    
    def create_big_slider(self, parent, from_, to, command, initial_value, name=""):
        slider_frame = tk.Frame(parent, bg=self.colors['card_bg'])
        slider_frame.pack(fill=tk.X, pady=15)
        
        slider = tk.Scale(slider_frame,
                         from_=from_, to=to,
                         orient=tk.HORIZONTAL,
                         length=450,
                         width=45,
                         sliderlength=65,
                         showvalue=False,
                         bg=self.colors['card_bg'],
                         fg=self.colors['fg'],
                         troughcolor=self.colors['slider_bg'],
                         activebackground=self.colors['accent'],
                         highlightbackground=self.colors['border'],
                         highlightthickness=0,
                         bd=0,
                         command=command)
        slider.set(initial_value)
        slider.pack()
        
        slider.name = name
        slider.step = 5
        
        return slider
    
    def add_button(self, btn):
        self.all_widgets.append(btn)
        self.widget_types.append('button')
    
    def add_slider(self, slider, name):
        self.all_widgets.append(slider)
        self.widget_types.append('slider')
    
    def create_all_controls(self):
        """Create all control sections"""
        logging.info("Creating UI controls...")
        
        # Add a status bar showing suspended app
        if self.app_suspender.suspended_pids:
            status_frame = tk.Frame(self.scrollable_frame, bg=self.colors['card_bg'], height=40)
            status_frame.pack(fill=tk.X, pady=5, padx=10)
            status_frame.pack_propagate(False)
            
            status_label = tk.Label(status_frame, 
                                   text="🎮 Game suspended while menu is open",
                                   font=('Arial', 12),
                                   bg=self.colors['card_bg'],
                                   fg=self.colors['accent'])
            status_label.pack(pady=10)
        
        # DISPLAY SECTION
        display_card = ttk.LabelFrame(self.scrollable_frame, text="🖥️ DISPLAY",
                                     style='Card.TLabelframe', padding="25")
        display_card.pack(fill=tk.X, pady=10, padx=10)
        
        current_brightness = self.get_current_brightness()
        
        brightness_value_frame = tk.Frame(display_card, bg=self.colors['card_bg'])
        brightness_value_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.brightness_label = tk.Label(brightness_value_frame,
                                        text=f"{int(current_brightness)}%",
                                        font=('Arial', 40, 'bold'),
                                        bg=self.colors['card_bg'],
                                        fg=self.colors['accent'])
        self.brightness_label.pack()
        
        self.brightness_slider = self.create_big_slider(
            display_card, 1, 100, self.on_brightness_change,
            current_brightness, "brightness"
        )
        self.add_slider(self.brightness_slider, "brightness")
        
        brightness_preset_frame = tk.Frame(display_card, bg=self.colors['card_bg'])
        brightness_preset_frame.pack(fill=tk.X, pady=15)
        
        presets = [("🌙 Night", 20), ("☀️ Indoor", 60), ("☀️ Full", 100)]
        
        for label, level in presets:
            btn = tk.Button(brightness_preset_frame, text=label,
                          font=('Arial', 16), bg=self.colors['button_bg'],
                          fg=self.colors['fg'], bd=0, padx=20, pady=15,
                          cursor='hand2', activebackground=self.colors['button_hover'],
                          activeforeground=self.colors['fg'],
                          command=lambda l=level: self.set_brightness(l))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
            self.add_button(btn)
        
        # AUDIO SECTION
        audio_card = ttk.LabelFrame(self.scrollable_frame, text="🔊 AUDIO",
                                   style='Card.TLabelframe', padding="25")
        audio_card.pack(fill=tk.X, pady=10, padx=10)
        
        current_volume = self.get_current_volume()
        
        volume_value_frame = tk.Frame(audio_card, bg=self.colors['card_bg'])
        volume_value_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.volume_label = tk.Label(volume_value_frame,
                                    text=f"{int(current_volume)}%",
                                    font=('Arial', 40, 'bold'),
                                    bg=self.colors['card_bg'],
                                    fg=self.colors['accent'])
        self.volume_label.pack()
        
        self.volume_slider = self.create_big_slider(
            audio_card, 0, 100, self.on_volume_change,
            current_volume, "volume"
        )
        self.add_slider(self.volume_slider, "volume")
        
        audio_control_frame = tk.Frame(audio_card, bg=self.colors['card_bg'])
        audio_control_frame.pack(fill=tk.X, pady=15)
        
        self.mute_btn = tk.Button(audio_control_frame, text="🔇 MUTE",
                                font=('Arial', 16, 'bold'),
                                bg=self.colors['button_bg'], fg=self.colors['fg'],
                                bd=0, padx=20, pady=15, cursor='hand2',
                                activebackground=self.colors['button_hover'],
                                activeforeground=self.colors['fg'],
                                command=self.toggle_mute)
        self.mute_btn.pack(side=tk.LEFT, padx=5)
        self.add_button(self.mute_btn)
        
        for level, label in [(50, "50%"), (100, "100%")]:
            btn = tk.Button(audio_control_frame, text=label, font=('Arial', 16),
                          bg=self.colors['button_bg'], fg=self.colors['fg'],
                          bd=0, padx=20, pady=15, cursor='hand2',
                          activebackground=self.colors['button_hover'],
                          activeforeground=self.colors['fg'],
                          command=lambda l=level: self.set_volume(l))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
            self.add_button(btn)
        
        # SCRIPTS SECTION
        scripts = self.get_scripts_list()
        if scripts:
            scripts_card = ttk.LabelFrame(self.scrollable_frame, text="📋 SCRIPTS",
                                         style='Card.TLabelframe', padding="25")
            scripts_card.pack(fill=tk.X, pady=10, padx=10)
            
            for name, command, color in scripts:
                btn = tk.Button(scripts_card, text=name, font=('Arial', 16),
                              bg=color, fg=self.colors['fg'], bd=0,
                              padx=20, pady=18, cursor='hand2',
                              activebackground=self.colors['button_hover'],
                              activeforeground=self.colors['fg'],
                              command=lambda cmd=command: self.run_command(cmd))
                btn.pack(fill=tk.X, pady=4)
                self.add_button(btn)
        
        # POWER SECTION
        power_card = ttk.LabelFrame(self.scrollable_frame, text="⚡ POWER",
                                   style='Card.TLabelframe', padding="25")
        power_card.pack(fill=tk.X, pady=10, padx=10)
        
        power_scripts = [
            ("💤 Suspend", "systemctl suspend", self.colors['button_bg']),
            ("🔄 Restart", "systemctl reboot", self.colors['close_btn']),
            ("⏻ Shutdown", "systemctl poweroff", self.colors['close_btn']),
        ]
        
        for name, command, color in power_scripts:
            btn = tk.Button(power_card, text=name, font=('Arial', 16),
                          bg=color, fg=self.colors['fg'], bd=0,
                          padx=20, pady=18, cursor='hand2',
                          activebackground=self.colors['button_hover'],
                          activeforeground=self.colors['fg'],
                          command=lambda cmd=command: self.run_command(cmd))
            btn.pack(fill=tk.X, pady=4)
            self.add_button(btn)
        
        bottom_padding = tk.Frame(self.scrollable_frame, bg=self.colors['bg'], height=20)
        bottom_padding.pack(fill=tk.X)
        
        if self.all_widgets:
            self.set_focus(0)
        
        logging.info("UI controls created")
    
    def get_current_brightness(self):
        try:
            result = subprocess.run(['brightnessctl', 'get'], 
                                   capture_output=True, text=True)
            if result.stdout:
                current = int(result.stdout.strip())
                max_result = subprocess.run(['brightnessctl', 'max'],
                                          capture_output=True, text=True)
                if max_result.stdout:
                    max_val = int(max_result.stdout.strip())
                    percentage = int((current / max_val) * 100)
                    logging.debug(f"Current brightness: {percentage}%")
                    return percentage
        except Exception as e:
            logging.error(f"Error getting brightness: {e}")
        return self.config.get('brightness', 100)
    
    def set_brightness(self, value):
        try:
            value = int(value)
            value = max(1, min(100, value))
            
            subprocess.run(['brightnessctl', 'set', f'{value}%'],
                         check=True, capture_output=True)
            
            self.brightness_slider.set(value)
            self.brightness_label.config(text=f"{value}%")
            self.config['brightness'] = value
            
            logging.debug(f"Brightness set to {value}%")
        except Exception as e:
            logging.error(f"Error setting brightness: {e}")
    
    def on_brightness_change(self, value):
        self.set_brightness(float(value))
    
    def get_current_volume(self):
        try:
            result = subprocess.run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'],
                                  capture_output=True, text=True)
            if '%' in result.stdout:
                match = re.search(r'(\d+)%', result.stdout)
                if match:
                    volume = float(match.group(1))
                    logging.debug(f"Current volume: {volume}%")
                    return volume
        except Exception as e:
            logging.error(f"Error getting volume: {e}")
        return self.config.get('volume', 50)
    
    def on_volume_change(self, value):
        volume = float(value)
        self.volume_label.config(text=f"{int(volume)}%")
        self.set_volume(volume)
    
    def set_volume(self, value):
        try:
            self.volume_slider.set(value)
            self.volume_label.config(text=f"{int(value)}%")
            
            percentage = int(value)
            
            subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', 
                          f'{percentage}%'], 
                         check=True, capture_output=True)
            
            self.config['volume'] = value
            
            if value == 0:
                self.mute_btn.config(text="🔊 UNMUTE")
            else:
                self.mute_btn.config(text="🔇 MUTE")
            
            logging.debug(f"Volume set to {value}%")
        except Exception as e:
            logging.error(f"Error setting volume: {e}")
    
    def toggle_mute(self):
        try:
            check_mute = subprocess.run(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'],
                                      capture_output=True, text=True)
            
            subprocess.run(['pactl', 'set-sink-mute', '@DEFAULT_SINK@', 'toggle'],
                         check=True, capture_output=True)
            
            if 'yes' in check_mute.stdout.lower():
                self.mute_btn.config(text="🔇 MUTE")
                logging.debug("Muted")
            else:
                self.mute_btn.config(text="🔊 UNMUTE")
                logging.debug("Unmuted")
        except Exception as e:
            logging.error(f"Error toggling mute: {e}")
    
    def run_command(self, command):
        try:
            logging.info(f"Running command: {command}")
            subprocess.Popen(command, shell=True)
        except Exception as e:
            logging.error(f"Error running command {command}: {e}")
    
    def navigate_up(self):
        if self.all_widgets:
            new_index = (self.current_focus_index - 1) % len(self.all_widgets)
            self.set_focus(new_index)
    
    def navigate_down(self):
        if self.all_widgets:
            new_index = (self.current_focus_index + 1) % len(self.all_widgets)
            self.set_focus(new_index)
    
    def navigate_left(self):
        if self.widget_types[self.current_focus_index] == 'slider':
            self.slider_decrease()
        else:
            self.navigate_up()
    
    def navigate_right(self):
        if self.widget_types[self.current_focus_index] == 'slider':
            self.slider_increase()
        else:
            self.navigate_down()
    
    def set_focus(self, index):
        if not self.all_widgets:
            return
        
        self.remove_highlight()
        
        self.current_focus_index = index
        widget = self.all_widgets[self.current_focus_index]
        widget_type = self.widget_types[self.current_focus_index]
        self.focused_widget = widget
        
        if widget_type == 'button':
            widget.original_bg = widget.cget('bg')
            widget.configure(bg=self.colors['highlight'], fg='#000000')
        else:
            widget.original_trough = widget.cget('troughcolor')
            widget.configure(troughcolor=self.colors['highlight'])
        
        self.root.update_idletasks()
        
        widget_y = widget.winfo_y()
        canvas_height = self.canvas.winfo_height()
        
        current_scroll = self.canvas.canvasy(0)
        visible_bottom = current_scroll + canvas_height
        
        if widget_y + widget.winfo_height() > visible_bottom:
            scroll_to = (widget_y + widget.winfo_height() - canvas_height) / self.scrollable_frame.winfo_height()
            self.canvas.yview_moveto(scroll_to)
        elif widget_y < current_scroll:
            scroll_to = widget_y / self.scrollable_frame.winfo_height()
            self.canvas.yview_moveto(scroll_to)
    
    def remove_highlight(self):
        if self.focused_widget:
            widget = self.focused_widget
            if hasattr(widget, 'original_trough'):
                widget.configure(troughcolor=widget.original_trough)
            elif hasattr(widget, 'original_bg'):
                widget.configure(bg=widget.original_bg, fg=self.colors['fg'])
            self.focused_widget = None
    
    def slider_increase(self):
        if (self.all_widgets and 
            self.widget_types[self.current_focus_index] == 'slider'):
            slider = self.all_widgets[self.current_focus_index]
            current = slider.get()
            new_value = min(slider.cget('to'), current + slider.step)
            slider.set(new_value)
            if slider.name == 'brightness':
                self.on_brightness_change(new_value)
            elif slider.name == 'volume':
                self.on_volume_change(new_value)
    
    def slider_decrease(self):
        if (self.all_widgets and 
            self.widget_types[self.current_focus_index] == 'slider'):
            slider = self.all_widgets[self.current_focus_index]
            current = slider.get()
            new_value = max(slider.cget('from'), current - slider.step)
            slider.set(new_value)
            if slider.name == 'brightness':
                self.on_brightness_change(new_value)
            elif slider.name == 'volume':
                self.on_volume_change(new_value)
    
    def keyboard_navigate(self, event):
        if event.keysym == 'Tab':
            if event.state & 0x1:
                self.navigate_up()
            else:
                self.navigate_down()
            return 'break'
    
    def get_scripts_list(self):
        scripts = [
            ("🔒 Lock Screen", "loginctl lock-session", self.colors['button_bg']),
            ("📸 Screenshot", "gnome-screenshot -i", self.colors['button_bg']),
            ("🌙 Night Light", "redshift -O 3500", self.colors['button_bg']),
            ("☀️ Reset Night Light", "redshift -x", self.colors['button_bg']),
        ]
        return scripts
    
    def load_config(self):
        self.config = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                logging.debug(f"Loaded config: {self.config}")
            except Exception as e:
                logging.error(f"Error loading config: {e}")
    
    def save_config(self):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            logging.debug(f"Saved config: {self.config}")
        except Exception as e:
            logging.error(f"Error saving config: {e}")

def main():
    logging.info("=" * 50)
    logging.info("Quick Access Menu starting up")
    logging.info(f"Python version: {sys.version}")
    logging.info(f"PID: {os.getpid()}")
    logging.info(f"DISPLAY: {os.environ.get('DISPLAY', 'Not set')}")
    
    script_name = os.path.basename(__file__)
    
    # Check for existing instances (toggle behavior)
    try:
        result = subprocess.run(['pgrep', '-f', script_name], capture_output=True, text=True)
        if result.stdout:
            pids = result.stdout.strip().split('\n')
            current_pid = str(os.getpid())
            
            other_pids = [pid for pid in pids if pid != current_pid]
            
            if other_pids:
                logging.info(f"Found existing instance(s): {other_pids}, killing them...")
                for pid in other_pids:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        logging.info(f"Killed PID: {pid}")
                    except Exception as e:
                        logging.error(f"Error killing PID {pid}: {e}")
                logging.info("Existing instances killed. Exiting.")
                sys.exit(0)
    except Exception as e:
        logging.error(f"Error checking instances: {e}")
    
    logging.info("No existing instance found, launching...")
    
    # Create app suspender and suspend the focused app
    app_suspender = AppSuspender()
    app_suspender.suspend_focused_app()
    
    # Launch our app
    root = tk.Tk()
    app = QuickAccessMenu(root, app_suspender)
    
    try:
        root.mainloop()
    except Exception as e:
        logging.error(f"Error during main loop: {e}")
    finally:
        # Resume the app when we exit
        app_suspender.resume_app()
        logging.info("Quick Access Menu closed, resumed suspended app")
    
    logging.info("Quick Access Menu exiting")
    logging.info("=" * 50)

if __name__ == "__main__":
    main()
