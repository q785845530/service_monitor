#!/usr/bin/env python3
"""
跨平台服务监控工具
支持 Debian (systemd) 和 Windows (Service Control Manager)
功能：
  - 多页签，每个页签对应一个服务
  - 启动清单：列出可管理的服务
  - 实时日志：类似 journalctl -f 的实时输出
  - 启动/停止/重启服务
"""

import os
import sys
import platform
import subprocess
import threading
from typing import List, Dict, Optional

from PyQt6.QtCore import (
    QThread, pyqtSignal, Qt, QTimer, QProcess, QProcessEnvironment
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QComboBox,
    QTextEdit, QMessageBox, QGroupBox, QTabWidget, QListWidget,
    QListWidgetItem, QSplitter, QCheckBox, QStatusBar, QToolBar,
    QFileDialog, QInputDialog, QProgressBar
)
from PyQt6.QtGui import QFont, QTextCursor, QAction, QIcon

# ---------- 平台识别 ----------
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ============================================================
#                 Systemd (Linux) 封装
# ============================================================

class SystemdBackend:
    """Linux systemd 服务后端"""

    @staticmethod
    def list_services() -> List[Dict[str, str]]:
        """列出所有服务单元及其状态"""
        try:
            # 使用 --no-pager 防止卡在分页器
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service",
                 "--all", "--no-pager", "--no-legend"],
                capture_output=True, text=True, timeout=10
            )
            services = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    unit = parts[0]
                    load = parts[1]
                    active = parts[2]
                    sub = parts[3]
                    desc = " ".join(parts[4:])
                    services.append({
                        "name": unit,
                        "load": load,
                        "active": active,
                        "sub": sub,
                        "description": desc,
                    })
            return services
        except Exception as e:
            return [{"name": "错误", "description": str(e)}]

    @staticmethod
    def get_status(service: str) -> str:
        """获取服务的当前状态"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def start_service(service: str) -> tuple:
        try:
            r = subprocess.run(
                ["sudo", "systemctl", "start", service],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0, r.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def stop_service(service: str) -> tuple:
        try:
            r = subprocess.run(
                ["sudo", "systemctl", "stop", service],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0, r.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def restart_service(service: str) -> tuple:
        try:
            r = subprocess.run(
                ["sudo", "systemctl", "restart", service],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0, r.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def journalctl_command(service: str, lines: int = 200) -> List[str]:
        """构造 journalctl 实时日志命令"""
        return [
            "sudo", "journalctl", "-u", service,
            "-n", str(lines), "-f", "--no-pager",
            "-o", "short-iso"
        ]


# ============================================================
#                 Windows 服务封装
# ============================================================

class WindowsBackend:
    """Windows 服务后端 (通过 PowerShell)"""

    @staticmethod
    def _powershell(cmd: str) -> str:
        """执行 PowerShell 命令"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=20
            )
            return result.stdout
        except Exception as e:
            return f"ERROR: {e}"

    @staticmethod
    def list_services() -> List[Dict[str, str]]:
        """列出所有 Windows 服务"""
        ps = (
            "Get-Service | Select-Object Name, Status, DisplayName | "
            "ForEach-Object { "
            "$_.Name + '|' + $_.Status + '|' + $_.DisplayName "
            "}"
        )
        out = WindowsBackend._powershell(ps)
        services = []
        for line in out.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            services.append({
                "name": parts[0],
                "active": parts[1].lower(),
                "sub": parts[1].lower(),
                "load": "loaded",
                "description": parts[2],
            })
        return services

    @staticmethod
    def get_status(service: str) -> str:
        ps = f"(Get-Service -Name '{service}').Status"
        return WindowsBackend._powershell(ps).strip().lower() or "unknown"

    @staticmethod
    def _control(service: str, action: str) -> tuple:
        """action: Start / Stop / Restart"""
        ps = f"{action}-Service -Name '{service}'"
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=60
            )
            return r.returncode == 0, r.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def start_service(service: str) -> tuple:
        return WindowsBackend._control(service, "Start")

    @staticmethod
    def stop_service(service: str) -> tuple:
        return WindowsBackend._control(service, "Stop")

    @staticmethod
    def restart_service(service: str) -> tuple:
        return WindowsBackend._control(service, "Restart")

    @staticmethod
    def journalctl_command(service: str, lines: int = 200) -> Optional[List[str]]:
        """
        Windows 上模拟 journalctl -f：使用 PowerShell Get-Content 实时读取
        需要服务本身有日志文件路径。这里返回 None 表示让 UI 显示说明。
        """
        return None


# 选择后端
if IS_LINUX:
    Backend = SystemdBackend
elif IS_WINDOWS:
    Backend = WindowsBackend
else:
    Backend = SystemdBackend


# ============================================================
#                 日志实时监控线程
# ============================================================

class LogStreamer(QThread):
    """在后台线程中运行 journalctl -f 或 PowerShell 命令，实时输出日志"""
    log_line = pyqtSignal(str)
    error = pyqtSignal(str)
    finished_stream = pyqtSignal()

    def __init__(self, cmd: List[str], parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            env = os.environ.copy()
            # 让 sudo 不阻塞（如果已配置 NOPASSWD）
            if IS_LINUX:
                env["SYSTEMD_COLORS"] = "0"
            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            for line in iter(process.stdout.readline, ""):
                if self._stop:
                    break
                self.log_line.emit(line.rstrip("\n"))
            process.stdout.close()
            process.terminate()
            process.wait(timeout=5)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished_stream.emit()


# ============================================================
#                 单个服务的监控页签
# ============================================================

class ServiceTab(QWidget):
    """每个服务一个页签，包含日志输出、状态、控制按钮"""

    def __init__(self, service_name: str, parent=None):
        super().__init__(parent)
        self.service_name = service_name
        self.streamer: Optional[LogStreamer] = None

        self._build_ui()
        self._refresh_status()

        # 定时刷新状态
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start(5000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---------- 顶部：服务名与状态 ----------
        top = QHBoxLayout()
        self.lbl_name = QLabel(f"服务: <b>{self.service_name}</b>")
        self.lbl_name.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.lbl_name)

        self.lbl_status = QLabel("状态: -")
        self.lbl_status.setStyleSheet("font-weight: bold;")
        top.addWidget(self.lbl_status)

        top.addStretch()

        self.btn_start = QPushButton("启动")
        self.btn_start.clicked.connect(self._start)
        top.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._stop)
        top.addWidget(self.btn_stop)

        self.btn_restart = QPushButton("重启")
        self.btn_restart.clicked.connect(self._restart)
        top.addWidget(self.btn_restart)

        layout.addLayout(top)

        # ---------- 工具条 ----------
        toolbar = QHBoxLayout()

        self.btn_tail = QPushButton("开始实时监控")
        self.btn_tail.setCheckable(True)
        self.btn_tail.toggled.connect(self._toggle_tail)
        toolbar.addWidget(self.btn_tail)

        toolbar.addWidget(QLabel("显示行数:"))
        self.combo_lines = QComboBox()
        self.combo_lines.addItems(["100", "200", "500", "1000", "5000"])
        self.combo_lines.setCurrentText("200")
        toolbar.addWidget(self.combo_lines)

        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        toolbar.addWidget(self.chk_autoscroll)

        toolbar.addStretch()

        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear)
        toolbar.addWidget(self.btn_clear)

        self.btn_save = QPushButton("保存日志")
        self.btn_save.clicked.connect(self._save)
        toolbar.addWidget(self.btn_save)

        layout.addLayout(toolbar)

        # ---------- 日志输出 ----------
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Monospace", 9))
        self.txt_log.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        )
        layout.addWidget(self.txt_log, stretch=1)

    # ---------- 状态 ----------
    def _refresh_status(self):
        status = Backend.get_status(self.service_name)
        color = "#2ecc71" if status == "active" or status == "running" else "#e74c3c"
        self.lbl_status.setText(f"状态: <span style='color:{color}'>{status}</span>")
        self.lbl_status.setTextFormat(Qt.TextFormat.RichText)

    # ---------- 日志流控制 ----------
    def _toggle_tail(self, checked: bool):
        if checked:
            self._start_tail()
        else:
            self._stop_tail()

    def _start_tail(self):
        if self.streamer and self.streamer.isRunning():
            return
        if IS_WINDOWS:
            # Windows 下 journalctl 不可用，提示用户
            self.txt_log.append(
                "[提示] Windows 平台暂不支持实时 journalctl 日志。\n"
                "如果需要查看服务日志，请在服务自身的日志目录查看，\n"
                "或使用 'Get-EventLog' / 'Get-WinEvent' PowerShell 命令。\n"
            )
            self.btn_tail.setChecked(False)
            return

        cmd = Backend.journalctl_command(
            self.service_name,
            int(self.combo_lines.currentText())
        )
        self.streamer = LogStreamer(cmd, self)
        self.streamer.log_line.connect(self._append_line)
        self.streamer.error.connect(lambda e: self.txt_log.append(f"[错误] {e}"))
        self.streamer.finished_stream.connect(self._on_stream_finished)
        self.streamer.start()

    def _stop_tail(self):
        if self.streamer:
            self.streamer.stop()
            self.streamer.wait(2000)
            self.streamer = None

    def _on_stream_finished(self):
        self.btn_tail.setChecked(False)

    def _append_line(self, line: str):
        self.txt_log.append(line)
        if self.chk_autoscroll.isChecked():
            cursor = self.txt_log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.txt_log.setTextCursor(cursor)

    def _clear(self):
        self.txt_log.clear()

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", f"{self.service_name}.log",
            "日志文件 (*.log *.txt);;所有文件 (*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            QMessageBox.information(self, "保存成功", f"日志已保存到:\n{path}")

    # ---------- 服务控制 ----------
    def _start(self):
        ok, err = Backend.start_service(self.service_name)
        if ok:
            self.txt_log.append(f"[操作] 启动 {self.service_name} 成功")
            self._refresh_status()
        else:
            QMessageBox.critical(self, "启动失败", err)

    def _stop(self):
        ok, err = Backend.stop_service(self.service_name)
        if ok:
            self.txt_log.append(f"[操作] 停止 {self.service_name} 成功")
            self._refresh_status()
        else:
            QMessageBox.critical(self, "停止失败", err)

    def _restart(self):
        ok, err = Backend.restart_service(self.service_name)
        if ok:
            self.txt_log.append(f"[操作] 重启 {self.service_name} 成功")
            self._refresh_status()
        else:
            QMessageBox.critical(self, "重启失败", err)

    def close_stream(self):
        self._stop_tail()


# ============================================================
#                 主窗口
# ============================================================

class ServiceMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("服务监控 - Service Monitor")
        self.resize(1100, 750)
        self.tabs: Dict[str, ServiceTab] = {}

        self._build_ui()
        self.refresh_service_list()

    def _build_ui(self):
        # 工具栏
        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)

        act_refresh = QAction("刷新服务列表", self)
        act_refresh.triggered.connect(self.refresh_service_list)
        toolbar.addAction(act_refresh)

        act_open = QAction("打开指定服务", self)
        act_open.triggered.connect(self.open_service_dialog)
        toolbar.addAction(act_open)

        toolbar.addSeparator()

        act_close_all = QAction("关闭所有页签", self)
        act_close_all.triggered.connect(self.close_all_tabs)
        toolbar.addAction(act_close_all)

        # 主布局
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # 左侧：服务列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("<b>启动清单 / 服务列表</b>"))

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索服务名或描述...")
        self.search_box.textChanged.connect(self._filter_services)
        left_layout.addWidget(self.search_box)

        self.list_services = QListWidget()
        self.list_services.itemDoubleClicked.connect(self._open_selected)
        left_layout.addWidget(self.list_services, stretch=1)

        btn_open_selected = QPushButton("打开选中服务")
        btn_open_selected.clicked.connect(self._open_selected)
        left_layout.addWidget(btn_open_selected)

        splitter.addWidget(left)

        # 右侧：页签
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        right_layout.addWidget(self.tab_widget)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(
            f"平台: {platform.system()} {platform.release()}"
        )

        # 保存全部服务信息用于搜索
        self.all_services: List[Dict[str, str]] = []

    # ---------- 刷新服务列表 ----------
    def refresh_service_list(self):
        self.status.showMessage("正在获取服务列表...")
        self.all_services = Backend.list_services()
        self._populate_list(self.all_services)
        self.status.showMessage(f"共 {len(self.all_services)} 个服务", 3000)

    def _populate_list(self, services: List[Dict[str, str]]):
        self.list_services.clear()
        for svc in services:
            name = svc.get("name", "?")
            desc = svc.get("description", "")
            active = svc.get("active", "")
            icon = "🟢" if active in ("active", "running") else "⚪"
            item = QListWidgetItem(f"{icon} {name}  —  {desc}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_services.addItem(item)

    def _filter_services(self, text: str):
        text = text.lower()
        filtered = [
            s for s in self.all_services
            if text in s.get("name", "").lower()
            or text in s.get("description", "").lower()
        ]
        self._populate_list(filtered)

    # ---------- 打开页签 ----------
    def _open_selected(self):
        item = self.list_services.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self.open_service(name)

    def open_service_dialog(self):
        name, ok = QInputDialog.getText(
            self, "打开服务", "输入服务名称（例如 llama-server2.service 或 nginx）："
        )
        if ok and name.strip():
            self.open_service(name.strip())

    def open_service(self, name: str):
        if name in self.tabs:
            idx = self.tab_widget.indexOf(self.tabs[name])
            self.tab_widget.setCurrentIndex(idx)
            return
        tab = ServiceTab(name)
        self.tabs[name] = tab
        self.tab_widget.addTab(tab, name)
        self.tab_widget.setCurrentWidget(tab)

    def _close_tab(self, index: int):
        widget = self.tab_widget.widget(index)
        if isinstance(widget, ServiceTab):
            widget.close_stream()
            self.tabs.pop(widget.service_name, None)
        self.tab_widget.removeTab(index)

    def close_all_tabs(self):
        while self.tab_widget.count() > 0:
            self._close_tab(0)

    def closeEvent(self, event):
        self.close_all_tabs()
        event.accept()


# ============================================================
#                 入口
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ServiceMonitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
