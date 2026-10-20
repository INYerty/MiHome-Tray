# 米家快捷控制 · Windows 托盘版

基于 [huanyuejue/MiHome-Windows](https://github.com/huanyuejue/MiHome-Windows)
的派生版本，上游基线 `22655b8d0df07da44772833fbd33f696c0629b17`。
保留原作者版权和 GPL-3.0-or-later 许可证。本项目不是小米官方 Windows 客户端。

## 使用

1. 双击 Setup EXE 安装后打开「米家快捷控制」；或解压便携包，保持整个 `MiHome-Tray` 文件夹完整，运行 `MiHome-Tray.exe`。
2. 使用手机米家 App 扫描登录二维码。账号地区为中国大陆。验证码、风控验证由本人处理。
3. 右键托盘图标 → 管理托盘项目，选择挂灯、落地扇等设备。
4. 左键点击托盘图标打开快捷面板。挂灯和风扇的常用可读写属性直接显示；全部功能仍可点「详情」。
5. 设置中可启用开机自启动和启动后常驻托盘。默认不会擅自启用自启动。

## 本版本的变化

- v0.3.2：主窗口和托盘面板采用 Windows 11 Acrylic 毛玻璃、圆角和半透明卡片；系统不支持时使用主题背景。
- 按设备服务区分风扇本体和指示灯的电源，避免同名开关误控。
- 托盘和详情滑块直接跟随指针，拖动仅在本地预览，松手后提交；按规格步长量化，不发送无效的中间值。
- 从真实设备规格识别开关、亮度、色温、风速、模式和摇头，未发布的功能不显示。
- 面板展开时每 5 秒读取常用属性；操作提交后先显示等待确认，再回读，未匹配时重试两次。
- 不把写接口应答当作已执行；回读不一致时显示实际读数及未确认提示。
- 启动缓存后立即联网刷新；每 30 秒刷新设备在线列表，离线后重新上线可自动恢复。
- 托盘收藏的开关轮询不受主界面家庭/房间筛选影响，单次读失败不会永久停用。
- 属性值更新不销毁正在使用的控件，主题重建保留在途操作状态。
- 登录会话独立存放于 `account.dpapi`，以 Windows 当前用户的 DPAPI 加密。
  不导入其他工具的明文账号，不输出会话凭据。开发版数据在项目目录，便携版在 `%LOCALAPPDATA%\MiHome-Windows`。

## 范围与验收

首版使用社区库 mijiaAPI 5.x 的云接口，需要联网；没有局域网直连或 MQTT 推送。
轮询有延迟，「回读已确认」表示云接口读回了目标属性值，不保证物理设备已完成动作。
具体机型、属性、固件及账号风控须本人扫码后实测，不保证所有米家设备均能控制。
面板中的在线标识来自最近一次云设备列表；网络失败时会提示上次读数。

模拟测试和预览不会访问账号，示例设备不会保存到实际设备列表。
实机验收需要依次检查：挂灯开关/亮度/色温、风扇开关/风速/摇头、
手机端修改后的电脑回读、设备断电与恢复、电脑睡眠唤醒后刷新。

## 开发与打包

需要 Windows、Python 3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . pyinstaller pytest
.\.venv\Scripts\python.exe -m tests.smoke_test
.\.venv\Scripts\python.exe -m pytest tests/test_quick_controls.py -q
.\.venv\Scripts\python.exe run.py
.\.venv\Scripts\python.exe build_portable.py
```

输出 `dist/MiHome-Tray-portable.zip` 与 `dist/MiHome-Tray-source.zip`。
构建脚本在生成压缩包前会运行 EXE 的离线启动检查；失败时停止打包。
无控制台运行时的错误日志位于 `%LOCALAPPDATA%\MiHome-Windows\logs\app.log`。
运行 `build_installer.py` 可将便携目录制作成安装 EXE（需要 Inno Setup 6.7+）。
分发时保留许可证、源码包和依赖清单。上游原始说明保留于 `docs/UPSTREAM_README.md`。
