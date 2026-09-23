# service_monitor
一个完整的跨平台 PyQt6 应用，用于图形化管理 llama-server 类后台服务，支持多页签、启动清单、实时日志监控，并可在 Windows 和 Debian 上运行。
 
📦安装依赖
bash

pip install PyQt6

Debian 还需要：
bash

sudo apt install python3-pyqt6

📝 完整代码：service_monitor.py

🚀 使用方法
Debian 上运行
bash

# 1. 安装 PyQt6
sudo apt install python3-pyqt6

# 2. 运行
python service_monitor.py



📝 sudo 免密提示：
为了在 GUI 中调用 sudo systemctl 和 sudo journalctl，建议为当前用户配置 systemctl 和 journalctl 的免密：
bash

sudo visudo

添加一行：
text

你的用户名 ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/journalctl

Windows 上运行
bash

pip install PyQt6
python service_monitor.py

    管理员权限提示：Windows 上启动/停止服务需要管理员权限，请以管理员身份运行 Python 或打包后的 exe。

🎨 功能说明
功能	说明
左侧启动清单	列出系统所有服务，🟢 表示运行中，⚪ 表示停止
搜索框	快速过滤服务名或描述
双击服务	在右侧打开一个专属页签
多页签	每个服务独立一个页签，互不干扰
实时日志	点击"开始实时监控"启动 journalctl -f 等价的流式输出
自动滚动	勾选后日志始终滚动到底部
启动/停止/重启	页签顶部按钮直接操作服务
保存日志	可将当前日志导出为文件
状态自动刷新	每 5 秒刷新一次服务状态指示

📦 打包为可执行文件
Debian (Linux)
bash

pip install pyinstaller
pyinstaller --onefile --windowed --name ServiceMonitor service_monitor.py
# 输出: dist/ServiceMonitor

Windows
bash

pip install pyinstaller
pyinstaller --onefile --windowed --name ServiceMonitor service_monitor.py
# 输出: dist\ServiceMonitor.exe

    注意：PyInstaller 不能跨平台编译。要生成 Windows 的 .exe，必须在 Windows 上运行打包命令；要生成 Linux 的二进制，必须在 Linux 上打包。

💡 关键设计说明

    跨平台后端抽象：SystemdBackend 和 WindowsBackend 提供统一接口，主程序无需关心底层差异。

    实时日志线程：LogStreamer 用 QThread 运行 journalctl -f，通过信号槽把每一行日志传给 UI，不阻塞界面。

    sudo 处理：Debian 上通过 sudo 调用 systemctl/journalctl，建议配置 NOPASSWD 避免反复输密码。

    Windows 日志限制：Windows 没有 journalctl 等价物，代码中给出了提示，实际使用时可扩展为读取指定日志文件。

    资源清理：关闭页签或退出程序时，会正确终止所有后台日志流。

🔧 扩展建议

    Windows 日志：为 Windows 后端增加读取自定义日志文件的功能，比如读取 C:\logs\llama-server.log 并 tail -f。

    服务清单持久化：把用户添加的监控服务列表保存到 ~/.config/service-monitor.json，下次启动自动恢复。

    告警：当服务状态从 active 变为 inactive 时弹出通知。

    打包：用 PyInstaller 生成单文件，配合图标和版本信息。
