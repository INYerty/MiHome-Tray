# MiHome-Windows

米家设备的 Windows 桌面控制端。基于 [mijiaAPI](https://github.com/Do1e/mijia-api)
构建图形界面，扫码登录后即可在本地窗口中查看和控制家里的全部米家设备。

> **注意：当前项目仍处于早期版本。** 作者个人米家设备有限，无法对各类设备做针对性适配测试，因此 UI 和操作逻辑的完善度不算很高。不过基础使用（扫码登录、设备列表与常用控制、托盘、小爱语音等）已无大碍，但需适配更多设备功能则需要社区支持了。

## 功能

- **扫码登录**：米家 APP 扫二维码，登录凭据与上游依赖的 CLI 共用
- **设备列表**：按家庭、房间分组，实时显示在线状态，支持隐藏无功能设备
- **场景执行**：主页「场景」选项卡列出米家 APP 中创建的手动场景，一键执行（可在设置中隐藏该入口）
- **设备控制**：根据设备 spec 元数据自动生成控件——布尔属性映射开关、数值属性映射滑块（自动套用范围与步长）、枚举属性映射下拉框
- **动作执行**：设备支持的动作渲染为按钮，执行前二次确认
- **系统托盘**：最小化到托盘，支持快捷设备控制、场景一键执行、小爱音响快捷控制、小爱语音指令，托盘快捷窗口支持单列/双列卡片切换与设备/场景混排排序
- **主题配色**：深色 / 浅色 / 跟随系统（设置中切换，米家绿主题色两种模式一致）；托盘图标自动跟随 Windows 任务栏深浅色
- **界面缩放**：50%–200% 无级调节（叠加在系统缩放之上），需重启生效
- **开机自启动**：可选，写入当前用户注册表（HKCU Run）
- **小爱语音**：主界面右下角悬浮按钮，输入文字指令发送给在线小爱音箱，可指定默认输出音箱
- **版本检测**：启动时自动检查 GitHub Releases 新版本，也可在关于页手动检测
- **本地缓存**：设置、托盘/工作台配置与设备缓存存放在用户数据目录（详见下方路径说明）
- **上游可升级**：mijiaAPI 仅作为 PyPI 依赖锁定在 `>=5,<6`，升级后跑 `python -m tests.smoke_test` 即可确认兼容性

## 运行

要求 Python >= 3.10

### 一键运行

```powershell
git clone https://github.com/huanyuejue/MiHome-Windows.git
cd MiHome-Windows

# 双击 start.bat，或命令行执行：
start.bat
```

`start.bat` 自动完成：创建 venv → 安装依赖 → 启动程序，无需手动配置环境。

### 手动运行

```powershell
git clone https://github.com/huanyuejue/MiHome-Windows.git
cd MiHome-Windows

python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\python.exe run.py
```

首次启动会弹出扫码窗口；之后凭据长期复用，失效时再次扫码即可。

## 本地缓存与数据存储

程序运行时会在以下位置生成配置和缓存文件，方便用户备份或排查问题：

### 应用数据（Releases版）

路径：`%LOCALAPPDATA%\MiHome-Windows\`

| 文件 | 说明 |
|------|------|
| `settings.json` | 应用设置（主题、缩放、托盘、自启动等） |
| `tray.json` | 托盘快捷控制面板的设备/场景配置与显示顺序 |
| `workbench.json` | 工作台（设备详情页）的自定义布局 |
| `devices_cache.json` | 设备列表与状态缓存，启动时优先从缓存加载以加快首屏显示 |

> 路径中的 `%LOCALAPPDATA%` 通常为 `C:\Users\<用户名>\AppData\Local`。
> 旧版曾写在 exe 同目录，首次启动会自动迁移至此。

### 应用数据（源码模式）

路径：项目根目录（与 `run.py` 同级），文件名与Releases版一致

### 米家账号登录凭据

路径：`~/.config/mijia-api/auth.json`

这是 mijiaAPI 的认证文件，扫码登录后长期复用。失效时程序会自动提示重新扫码。

> 路径中的 `~` 在 Windows 上为 `C:\Users\<用户名>`。

## 构建可执行文件

项目使用 **[Nuitka](https://nuitka.net/)** 将 Python 源码编译打包为原生 Windows 可执行文件（standalone 模式：把 Python 解释器、全部依赖与资源文件整合进一个免安装目录，最终产出 `dist\MiHome-Windows.exe`）。Nuitka 是真编译器——把代码编译为 C 再编译为机器码，而非 PyInstaller 式的"打包字节码"，这也是需要 VS Build Tools 的原因。

### 前置条件

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | 需加入系统 PATH，构建脚本会自动创建 venv |
| VS Build Tools | 2022 | Nuitka 编译所需的 C 编译器，约 2 GB |

下载安装 VS Build Tools 2022：https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022

安装时勾选 **"使用 C++ 的桌面开发"** 工作负载。

### 一键构建

```powershell
git clone https://github.com/huanyuejue/MiHome-Windows.git
cd MiHome-Windows

# 双击 build_msvc.bat 或运行：
.\build.ps1
```

脚本自动完成：创建 venv → 安装依赖（含 Nuitka 本体）→ 激活 MSVC 编译环境 → Nuitka 编译 → 输出到 `dist/MiHome-Windows.exe`。

构建参数（打包资源清单、图标、排除项等）集中维护在 `build.ps1` 的 `$NuitkaArgs`；`build_msvc.bat` 只是转发到它的双击入口。

首次构建耗时较长（创建 venv + 下载依赖 + Nuitka 编译，通常 5–15 分钟，视机器而定）

## 项目结构

```
app/
├── core/                       # 核心层
│   ├── service.py              # mijiaAPI 适配层，全项目唯一 import mijiaAPI 的模块
│   ├── jobs.py                 # 串行任务队列，所有米家网络调用的后台通道
│   ├── models.py               # 数据模型
│   ├── _json_store.py          # JSON 持久化公共基础（数据目录/迁移/原子写）
│   ├── cache.py                # 设备缓存
│   ├── settings_store.py       # 应用设置持久化（含开机自启动注册表）
│   ├── tray_store.py           # 托盘配置持久化
│   ├── workbench_store.py      # 工作台配置持久化
│   ├── update_checker.py       # GitHub Releases 新版本检查（后台线程 + 信号）
│   └── restart.py              # 应用自重启（缩放等设置需重启生效时一键重启）
├── ui/                         # 界面层
│   ├── main_window.py          # 主窗口（无边框标题栏）
│   ├── tray/                   # 系统托盘
│   │   ├── quick_window.py     #   快捷控制面板（单列/双列卡片）
│   │   ├── audio_bar.py        #   音响控制栏
│   │   ├── controller.py       #   托盘控制器
│   │   └── manager_dialog.py   #   托盘项目管理对话框
│   ├── device_card.py          # 设备卡片组件
│   ├── device_dialog.py        # 设备详情对话框
│   ├── workbench_panel.py      # 工作台面板（属性/动作）
│   ├── workbench_item.py       # 工作台属性/动作项
│   ├── prop_widgets.py         # 属性控件（开关、滑块、下拉框）
│   ├── power_button.py         # 三态电源按钮（卡片/托盘/详情共用）
│   ├── overlay_dialog.py       # 遮罩对话框基类（详情/设置/抽屉共用）
│   ├── about_dialog.py         # 关于对话框（版本信息、手动检测更新）
│   ├── settings_dialog.py      # 设置对话框（主题界面/应用功能双分类）
│   ├── voice_fab.py            # 语音悬浮球
│   ├── toast.py                # 轻量通知浮层
│   ├── update_flow.py          # 版本检查界面流程（弹框提示/静默反馈）
│   ├── login_dialog.py         # 扫码登录对话框
│   ├── add_drawer.py           # 设备添加抽屉
│   ├── typewriter.py           # 打字机效果组件
│   ├── si_theme.py             # 主题中枢（深/浅调色板 + 全局 QSS 生成）
│   ├── theme_service.py        # 主题编排（跟随系统/浅色/深色）
│   ├── restart.py              # 应用自重启
│   ├── icon.ico / icon.png     # 应用图标
│   └── tray_icon.png / tray_icon_light.png  # 托盘图标
├── siui/                       # 内置 SiliconUI 组件库（GPL-3.0）
│   ├── components/             # UI 组件
│   ├── core/                   # 核心工具
│   └── gui/                    # 图形工具
└── __init__.py                 # 版本号 + 工具函数

tests/
├── smoke_test.py               # 上游升级后的接口兼容性自检
└── theme_test.py               # 主题切换回归（离屏像素断言）

run.py                          # 程序入口
start.bat                       # Windows 一键运行（双击运行）
build_msvc.bat                  # Windows 一键构建（双击运行，转发 build.ps1）
build.ps1                       # PowerShell 构建脚本（Nuitka 参数唯一来源）
pyproject.toml                  # 项目配置
LICENSE                         # GPL-3.0 许可证
```

## 依赖说明

| 包名 | 版本 | 用途 |
|------|------|------|
| mijiaAPI | >=5,<6 | 米家 API 封装 |
| PySide6 | >=6.7 | Qt6 绑定 |
| qrcode | >=8 | 登录二维码生成 |
| qtawesome | >=1.4 | Material Design 图标 |
| numpy | - | SiliconUI 动画插值 |
| typing_extensions | - | SiliconUI 在 Python 3.10 下所需的类型别名 |

## 开源许可

本项目基于 [GPL-3.0](LICENSE) 或更高版本发布。

### 第三方组件

本程序使用了以下 GPL-3.0 协议的开源组件，在此向原作者致谢：

- [mijia-api](https://github.com/Do1e/mijia-api) - 米家 API 封装
- [PySide6-SiliconUI](https://github.com/H1DDENADM1N/PySide6-SiliconUI) - UI 组件库（已内置至 `app/siui/`）

对本项目代码的使用、修改与分发同样须遵循 GPL-3.0。

本程序不含任何担保。请自行承担使用风险，并遵守小米的服务条款。
