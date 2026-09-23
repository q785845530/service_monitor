#!/usr/bin/env python3
"""
配置文件管理器
负责加载、保存、生成默认配置文件
"""

import os
import json
import platform
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_CONFIG = {
    "version": 1,
    "services": [
        # 预置的监控服务清单，可手动编辑
        {
            "name": "llama-server2.service",
            "alias": "LLaMA Server 2",
            "enabled": True,
            "auto_open": False,
            "auto_start_monitor": False,
        },
        {
            "name": "llama-server.service",
            "alias": "LLaMA Server",
            "enabled": True,
            "auto_open": False,
            "auto_start_monitor": False,
        },
    ],
    "ui": {
        "auto_scroll": True,
        "log_lines": 200,
        "status_refresh_interval_ms": 5000,
        "theme": "dark",
        "font_size": 9,
        "window_width": 1100,
        "window_height": 750,
    },
    "backend": {
        # Linux: systemd；Windows: windows
        "type": "auto",
        # Windows 上自定义日志文件目录（可选）
        "windows_log_dir": "C:/logs",
    },
    "advanced": {
        "sudo_no_password_hint": True,
        "max_log_buffer_lines": 10000,
    },
}


def get_config_dir() -> Path:
    """根据平台返回配置目录"""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "service-monitor"
    elif system == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "service-monitor"
    else:  # Linux 等
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "service-monitor"


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: Path = None):
        self.config_path = config_path or get_config_path()
        self.config: Dict[str, Any] = {}
        self.load()

    # ---------- 加载 ----------
    def load(self):
        """加载配置文件，不存在则生成默认配置"""
        if not self.config_path.exists():
            print(f"[配置] 未找到配置文件，生成默认配置: {self.config_path}")
            self.config = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
            self.save()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            # 合并默认配置，确保新版本新增字段也有默认值
            self._merge_defaults()
            print(f"[配置] 已加载: {self.config_path}")
        except json.JSONDecodeError as e:
            print(f"[配置] 文件损坏，使用默认配置: {e}")
            self.config = json.loads(json.dumps(DEFAULT_CONFIG))
            # 备份损坏文件
            backup = self.config_path.with_suffix(".json.bak")
            self.config_path.rename(backup)
            self.save()

    def _merge_defaults(self):
        """递归合并默认配置，避免旧配置文件缺少新字段"""
        def merge(base: dict, default: dict):
            for key, value in default.items():
                if key not in base:
                    base[key] = value
                elif isinstance(value, dict) and isinstance(base.get(key), dict):
                    merge(base[key], value)
        merge(self.config, DEFAULT_CONFIG)

    # ---------- 保存 ----------
    def save(self):
        """保存配置到文件"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        print(f"[配置] 已保存: {self.config_path}")

    # ---------- 快捷访问 ----------
    def get(self, *keys, default=None):
        """按路径读取配置，例如 get('ui', 'log_lines')"""
        node = self.config
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def set(self, *keys, value):
        """按路径写入配置，例如 set('ui', 'log_lines', value=500)"""
        node = self.config
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()

    # ---------- 服务清单操作 ----------
    def get_services(self, only_enabled: bool = False) -> List[Dict]:
        services = self.config.get("services", [])
        if only_enabled:
            return [s for s in services if s.get("enabled", True)]
        return services

    def add_service(self, name: str, alias: str = "", auto_open: bool = False):
        """添加一个服务到清单"""
        for svc in self.config.setdefault("services", []):
            if svc["name"] == name:
                return False  # 已存在
        self.config["services"].append({
            "name": name,
            "alias": alias or name,
            "enabled": True,
            "auto_open": auto_open,
            "auto_start_monitor": False,
        })
        self.save()
        return True

    def remove_service(self, name: str) -> bool:
        """从清单中移除服务"""
        services = self.config.get("services", [])
        original_len = len(services)
        self.config["services"] = [s for s in services if s["name"] != name]
        if len(self.config["services"]) != original_len:
            self.save()
            return True
        return False

    def update_service(self, name: str, **kwargs) -> bool:
        """更新服务字段"""
        for svc in self.config.get("services", []):
            if svc["name"] == name:
                svc.update(kwargs)
                self.save()
                return True
        return False


# ---------- 供外部调用的单例 ----------
_config_manager: ConfigManager = None


def get_config() -> ConfigManager:
    """获取全局配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


if __name__ == "__main__":
    # 直接运行此文件时，仅生成默认配置并打印路径
    cfg = get_config()
    print(f"\n配置文件路径: {cfg.config_path}")
    print("\n当前配置内容:")
    print(json.dumps(cfg.config, indent=2, ensure_ascii=False))
