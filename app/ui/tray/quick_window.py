# SPDX-License-Identifier: GPL-3.0-or-later
# MiHome-Windows: 米家设备的 Windows 桌面控制端
# Copyright (C) 2026 MiHome-Windows contributors
"""托盘左键快捷窗口：设备/场景行、音频栏、小爱语音条与呼出动画。"""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta

from app.core import settings_store, tray_store
from app.core.jobs import JobExecutor
from app.core.models import DeviceInfo, SceneInfo, is_speaker
from app.core.quick_controls import QuickControlRegistry, supports_quick_controls
from app.ui.tray.device_controls import QuickDeviceCard
from app.core.service import MijiaService
from app.ui.power_button import PowerButton
from app.ui.si_theme import SiColors
from app.ui.toast import Toast
from app.ui.tray.audio_bar import _TrayAudioBar
from app.ui.typewriter import TypewriterPlaceholder
from app.ui.glass import prepare_glass, apply_glass, supported as glass_supported, tint


class TrayQuickWindow(QDialog):
    """托盘左键弹出的快捷操作面板。"""

    manage_requested = Signal()
    open_device_requested = Signal(str)  # did
    open_main_requested = Signal()
    presence_requested = Signal()

    def __init__(self, service: MijiaService, jobs: JobExecutor, parent=None, *, registry=None):
        super().__init__(parent)
        self._service = service
        self._jobs = jobs
        self._registry = registry or QuickControlRegistry(service, jobs, self)
        self._device_signature = None
        self._control_timer = QTimer(self)
        self._control_timer.setInterval(5000)
        self._control_timer.timeout.connect(self._refresh_controls)
        self._devices: list[DeviceInfo] = []
        self._known_power: dict[str, bool | None] = {}
        self._metrics: dict[str, str | None] = {}
        self._sub_labels: dict[str, QLabel] = {}
        self._sub_widths: dict[str, int] = {}
        self._columns: int = settings_store.get_tray_columns()
        self._detail_device = None
        self._sort_mode = False
        self._restoring_size = True
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(250)
        self._size_timer.timeout.connect(lambda: settings_store.set_tray_size(self.width(), self.height()))

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool |
                            (Qt.CustomizeWindowHint if glass_supported() else Qt.FramelessWindowHint))
        prepare_glass(self)
        if not glass_supported():
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(False)
        self.hide()

        # 保存引用：retheme 必须对控件自身重设样式——子控件自身样式表
        # 优先于窗口级样式表，只设窗口级会被构造时的旧样式盖住
        self._root = QFrame(self)
        self._root.setObjectName("trayQuickPanel")
        self._root.setStyleSheet(
            f"QFrame#trayQuickPanel {{ background: {SiColors.WINDOW_BG}; border: 1px solid {SiColors.LINE}; border-radius: 16px; }}")
        lay = QVBoxLayout(self._root)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(14)

        # 标题栏：房子（打开主窗口）+ 加号（管理）+ 关闭
        header = QHBoxLayout()
        header.setSpacing(6)
        upper_grip = QSizeGrip(self)
        upper_grip.setFixedSize(14, 14)
        upper_grip.setToolTip("拖动左上角放大小窗")
        header.addWidget(upper_grip, alignment=Qt.AlignTop | Qt.AlignLeft)
        title = QLabel("米家 · 快捷控制")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {SiColors.TEXT_PRIMARY}; background: transparent;")
        header.addWidget(title)
        header.addStretch(1)
        # 打开主窗口（房子图标）— 与 + 和 × 统一尺寸
        home_btn = QPushButton()
        home_btn.setFixedSize(22, 22)
        home_btn.setCursor(Qt.PointingHandCursor)
        home_btn.setToolTip("打开主窗口")
        home_btn.setIcon(qta.icon('mdi.home', color=SiColors.TEXT_PRIMARY))
        home_btn.setIconSize(QSize(16, 16))
        home_btn.setStyleSheet(
            f"QPushButton {{ background: {SiColors.SURFACE}; border: none; border-radius: 11px; }}"
            f"QPushButton:hover {{ background: {SiColors.BTN_HOVER}; }}")
        home_btn.setAutoDefault(False)
        home_btn.setDefault(False)
        home_btn.clicked.connect(self._open_main)
        header.addWidget(home_btn)
        # 单双列切换（放在打开主窗口右边）：图标表示当前列数，点击切换
        self._cols_btn = QPushButton()
        self._cols_btn.setFixedSize(22, 22)
        self._cols_btn.setCursor(Qt.PointingHandCursor)
        self._cols_btn.setIconSize(QSize(16, 16))
        self._cols_btn.setStyleSheet(
            f"QPushButton {{ background: {SiColors.SURFACE}; border: none; border-radius: 11px; }}"
            f"QPushButton:hover {{ background: {SiColors.BTN_HOVER}; }}")
        self._cols_btn.setAutoDefault(False)
        self._cols_btn.setDefault(False)
        self._cols_btn.clicked.connect(self._toggle_columns)
        self._refresh_cols_btn()
        header.addWidget(self._cols_btn)
        # 管理（加号线性图标）— 缩小
        add_btn = QPushButton()
        add_btn.setFixedSize(22, 22)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setToolTip("管理托盘项目")
        add_btn.setIcon(qta.icon('mdi.plus', color=f'{SiColors.TEXT_PRIMARY}'))
        add_btn.setIconSize(QSize(16, 16))
        add_btn.setStyleSheet(
            f"QPushButton {{ background: {SiColors.SURFACE}; border: none; border-radius: 11px; }}"
            f"QPushButton:hover {{ background: {SiColors.BTN_HOVER}; }}")
        add_btn.setAutoDefault(False)
        add_btn.setDefault(False)
        add_btn.clicked.connect(self.manage_requested.emit)
        header.addWidget(add_btn)
        # 关闭（叉号线性图标）— 缩小
        close = QPushButton()
        close.setFixedSize(22, 22)
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("关闭")
        close.setIcon(qta.icon('mdi.close', color=f'{SiColors.TEXT_PRIMARY}'))
        close.setIconSize(QSize(16, 16))
        close.setStyleSheet(
            f"QPushButton {{ background: {SiColors.SURFACE}; border: none; border-radius: 11px; }}"
            "QPushButton:hover { background: #c0392b; }")
        close.setAutoDefault(False)
        close.setDefault(False)
        close.clicked.connect(self.hide_animated)
        header.addWidget(close)
        lay.addLayout(header)

        # 滚动列表：列数可切换（1/2），可见行数固定 4 行
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        # 固定高度：可见 4 排卡片（56×4 + 间距6×3），单双列共用同一行高；
        # 窗口按上下栏显隐外扩
        self._scroll.setMinimumHeight(120)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; margin: 0 2px 0 0; }"
            f"QScrollBar::handle:vertical {{ background: {SiColors.SCROLLBAR}; border-radius: 3px; min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {SiColors.SCROLLBAR_HOVER}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._host)
        self._list_lay.setContentsMargins(0, 0, 6, 0)
        self._list_lay.setSpacing(12)
        self._scroll.setWidget(self._host)
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("QStackedWidget { background: transparent; }")
        self._stack.addWidget(self._scroll)
        self._detail_page = QWidget()
        self._detail_page.setObjectName("trayDetailPage")
        self._detail_page.setStyleSheet("QWidget#trayDetailPage { background: transparent; }")
        self._detail_lay = QVBoxLayout(self._detail_page)
        self._detail_lay.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("‹ 返回设备")
        back.setMinimumHeight(30)
        back.setAutoDefault(False)
        back.clicked.connect(self._back_to_devices)
        self._detail_lay.addWidget(back, alignment=Qt.AlignLeft)
        self._detail_scroll = QScrollArea()
        self._detail_scroll.setWidgetResizable(True)
        self._detail_scroll.setFrameShape(QFrame.NoFrame)
        self._detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._detail_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        self._detail_lay.addWidget(self._detail_scroll, 1)
        self._stack.addWidget(self._detail_page)
        lay.addWidget(self._stack, stretch=1)
        from app.ui.tray.quick_sort import QuickSortController
        self._sorter = QuickSortController(self._host, self._scroll.viewport(), self)
        self._sorter.order_changed.connect(self._save_quick_order)

        self._empty = QLabel("暂无托盘项目\n点击右上角 + 添加")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; background: transparent; font-size: 9pt;")
        self._empty.hide()
        lay.addWidget(self._empty)

        # 底部小爱输入条：有小爱音箱才显示，复用主页悬浮球同款交互
        self._voice_frame = QFrame()
        self._voice_frame.setObjectName("voiceInputBar")
        self._voice_frame.setFixedHeight(48)
        self._voice_frame.setStyleSheet(
            f"QFrame#voiceInputBar {{ background: {SiColors.CARD}; border: 1px solid {SiColors.LINE}; border-radius: 8px; }}")
        voice_lay = QHBoxLayout(self._voice_frame)
        voice_lay.setContentsMargins(10, 4, 10, 4)
        self._voice_edit = QLineEdit()
        self._voice_edit.setFont(QFont("Microsoft YaHei UI", 9))
        self._voice_edit.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {SiColors.TEXT_PRIMARY}; }}")
        self._voice_edit.installEventFilter(self)
        self._voice_edit.returnPressed.connect(self._emit_voice)
        voice_lay.addWidget(self._voice_edit)
        from app.ui.microphone_button import MicrophoneButton
        self._mic = MicrophoneButton(self, compact=True)
        self._mic.submitted.connect(self._voice_transcript)
        self._mic.status_changed.connect(self._voice_status)
        self._mic.failed.connect(lambda message: Toast.info(self, message, 4500))
        voice_lay.addWidget(self._mic)
        self._voice_frame.hide()
        # 占位打字机与主页悬浮球共用同一实现：常量、节奏、停留
        self._hint_full = "对小爱输入“打开卧室灯”，回车执行"
        self._typewriter = TypewriterPlaceholder(self._voice_edit, self._hint_full)

        # 底部输入框：占满宽度
        lay.addWidget(self._voice_frame)
        footer = QHBoxLayout()
        self._sort_btn = QPushButton("排列")
        self._sort_btn.setMinimumSize(48, 28)
        self._sort_btn.setCheckable(True)
        self._sort_btn.setAutoDefault(False)
        self._sort_btn.setToolTip("显示拖动手柄，调整小窗卡片顺序")
        self._sort_btn.toggled.connect(self._set_sort_mode)
        footer.addWidget(self._sort_btn)
        reset = QPushButton("重置大小")
        reset.setMinimumSize(68, 28)
        reset.setAutoDefault(False)
        reset.clicked.connect(self._reset_size)
        footer.addWidget(reset)
        self._hint = QLabel("拖角缩放")
        self._hint.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; font-size: 8pt;")
        footer.addWidget(self._hint, 1)
        grip = QSizeGrip(self)
        grip.setToolTip("拖动调整小窗大小")
        footer.addWidget(grip, alignment=Qt.AlignRight | Qt.AlignBottom)
        lay.addLayout(footer)

        # 音箱音频控制栏：不放在设备卡片内，顶部单独界面
        self._audio_bar = _TrayAudioBar(service, jobs, self)

        self._outer_lay = QVBoxLayout(self)
        self._outer_lay.setContentsMargins(0, 0, 0, 0)
        self._outer_lay.setSpacing(8)
        self._outer_lay.addWidget(self._audio_bar)
        self._outer_lay.addWidget(self._root)
        self.setMinimumSize(340, 360)
        size = settings_store.get_tray_size() or (400, 650)
        self.resize(*size)
        self._restoring_size = False
        self._tray_dids: list[str] = tray_store.load()
        # 场景与统一顺序缓存：呼出时从 tray_store 刷新（见 _rebuild / show_near_tray）
        self._tray_scenes: list[dict] | None = None
        self._tray_order: list[dict] | None = None
        # 呼出/隐藏动画与点击外部隐藏
        self._target_pos: QPoint | None = None
        self._show_anim: QParallelAnimationGroup | None = None
        self._hide_anim: QParallelAnimationGroup | None = None
        self._outside_filter_installed = False
        self._tray_visible: bool = False  # 显式呼出状态（Tool 窗口失焦时 isVisible 会误报 False）

    def nativeEvent(self, event_type, message):
        if glass_supported() and event_type == "windows_generic_MSG":
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE
                return True, 0
        return super().nativeEvent(event_type, message)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # QLineEdit already emitted returnPressed. QDialog's implicit default
        # button would also execute an unrelated audio/scene control here.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def is_animating(self) -> bool:
        """呼出/隐藏动画是否正在进行。"""
        return self._show_anim is not None or self._hide_anim is not None

    def abort_toggle_animation(self) -> None:
        """终止进行中的呼出/隐藏动画并复位透明度（托盘图标切换显隐用）。"""
        for anim in (self._show_anim, self._hide_anim):
            if anim is not None:
                try:
                    anim.stop()  # 中途停止不发 finished，须手动清理
                except Exception:
                    pass
                anim.deleteLater()
        self._show_anim = None
        self._hide_anim = None
        self.setWindowOpacity(1.0)

    def is_explicitly_visible(self) -> bool:
        """显式呼出状态（Tool 窗口失焦时 isVisible 会误报 False）。"""
        return self._tray_visible

    def _open_main(self) -> None:
        self.hide_animated()
        self.open_main_requested.emit()

    def _refresh_cols_btn(self) -> None:
        """图标与提示跟随当前列数：view-stream（横条堆叠）为单列，view-grid 为双列。"""
        if self._columns == 1:
            icon_name, tip = "mdi.view-stream-outline", "单列显示，点击切换双列"
        else:
            icon_name, tip = "mdi.view-grid-outline", "双列显示，点击切换单列"
        self._cols_btn.setIcon(qta.icon(icon_name, color=SiColors.TEXT_PRIMARY))
        self._cols_btn.setToolTip(tip)

    def _toggle_columns(self) -> None:
        self._columns = 1 if self._columns == 2 else 2
        settings_store.set_tray_columns(self._columns)
        self._refresh_cols_btn()
        if self._columns == 2 and self.width() < 700:
            self.resize(740, self.height())
        self._rebuild()

    def set_devices(self, devices: list[DeviceInfo], known_power: dict[str, bool | None]) -> None:
        """由主窗口在设备列表刷新后调用，传入全量设备与开关记忆。"""
        signature = tuple((d.did, d.name, d.model, d.room_name, d.online, d.spec_type) for d in devices)
        changed = signature != self._device_signature or self._tray_dids != tray_store.load() or self._tray_order != tray_store.load_order()
        self._device_signature = signature
        self._devices = list(devices)
        self._registry.update_devices(devices)
        self._known_power = dict(known_power)
        self._tray_dids = tray_store.load()
        self._tray_scenes = tray_store.load_scenes()
        self._tray_order = tray_store.load_order()
        self._update_audio_bar()
        self._update_voice_bar()
        if self.isVisible():
            if changed:
                self._rebuild()
                self._refresh_controls()
            else:
                self._apply_power(known_power)
            # 不再 adjustSize——它会按 sizeHint 漏算语音条/音频栏，导致窗口逐次缩短

    def set_metrics(self, metrics: dict[str, str | None]) -> None:
        """主窗口温湿度读数同步：更新内存并就地刷新可见行副标题。"""
        import shiboken6

        if not shiboken6.isValid(self):
            return
        self._metrics = dict(metrics)
        if not self.isVisible():
            return
        for did, text in metrics.items():
            sub = self._sub_labels.get(did)
            if sub is None or not shiboken6.isValid(sub):
                continue
            dev = next((d for d in self._devices if d.did == did), None)
            if dev is None:
                continue
            if dev.online:
                sub_text = f"{dev.room_name} | {text}" if text else dev.room_name
            else:
                sub_text = f"{dev.room_name} · 离线"
            self._set_elided(sub, sub_text, self._sub_widths.get(did))

    def _update_voice_bar(self) -> None:
        has_speaker = any(is_speaker(d) and d.online for d in self._devices)
        self._voice_frame.setVisible(has_speaker)
        self._typewriter.stop()
        if has_speaker and not self._mic.is_listening():
            self._voice_edit.setPlaceholderText("输入指令，或点击麦克风说话")
        self._sync_tray_height()

    def _pick_speaker(self) -> DeviceInfo | None:
        """输出音箱：设置的默认音箱（在线时）优先，否则第一个在线音箱。"""
        pref = settings_store.get_default_speaker_did()
        if pref:
            for d in self._devices:
                if d.did == pref and is_speaker(d) and d.online:
                    return d
        return next((d for d in self._devices if is_speaker(d) and d.online), None)

    def _update_audio_bar(self) -> None:
        # 有在线小爱音箱时显示音频控制栏；无则隐藏
        speaker = self._pick_speaker()
        if speaker is not None:
            self._audio_bar.set_speaker(speaker.did)
        else:
            self._audio_bar.set_speaker(None)
        self._sync_tray_height()

    def _sync_tray_height(self) -> None:
        # Layout owns the available space. Polling must never overwrite a user's size.
        if not hasattr(self, "_stack"):
            return
        from PySide6.QtGui import QGuiApplication
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.setMaximumSize(max(340, area.width() - 24), max(360, area.height() - 24))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_size_timer") and not self._restoring_size and self.isVisible():
            self._size_timer.start()
        if hasattr(self, "_grid") and self._grid is not None:
            self._reflow_grid()

    def _effective_columns(self) -> int:
        return self._columns if self.width() >= 680 else 1

    def _reflow_grid(self) -> None:
        grid = self._grid
        columns = self._effective_columns()
        if getattr(self, "_layout_columns", None) == columns:
            return
        widgets = []
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                widgets.append(item.widget())
        for column in range(max(2, grid.columnCount())):
            grid.setColumnStretch(column, int(column < columns))
        for index, widget in enumerate(widgets):
            grid.addWidget(widget, index // columns, index % columns)
        self._layout_columns = columns

    def _reset_size(self) -> None:
        self.resize(400 if self._columns == 1 else 740, 650)
        settings_store.set_tray_size(self.width(), self.height())

    def _set_sort_mode(self, enabled: bool) -> None:
        self._sort_mode = enabled
        self._sorter.set_enabled(enabled)
        self._hint.setText("拖柄排序" if enabled else "拖角缩放")

    def _save_quick_order(self, keys: list[str]) -> None:
        ordered = []
        for key in keys:
            kind, ident = key.split(":", 1)
            ordered.append({"type": kind, "id": ident})
        # Preserve selected items not currently present in the account snapshot.
        seen = {(item["type"], item["id"]) for item in ordered}
        ordered.extend(item for item in self._tray_order or []
                       if (item["type"], item["id"]) not in seen)
        self._tray_order = ordered
        tray_store.save_order(ordered)
        # Don't destroy a drag source while QDrag.exec is still unwinding.
        QTimer.singleShot(0, self._rebuild)

    def _back_to_devices(self) -> None:
        self._stack.setCurrentWidget(self._scroll)
        self._detail_device = None
        self._sort_btn.show()

    def _open_inline(self, did: str) -> None:
        device = next((d for d in self._devices if d.did == did), None)
        if device is None:
            return
        self._detail_device = device
        self._sort_btn.hide()
        self._empty.hide()
        body = QWidget()
        body.setObjectName("trayDetailBody")
        body.setStyleSheet("QWidget#trayDetailBody { background: transparent; }")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if is_speaker(device):
            from app.ui.speaker_commands import SpeakerCommands
            layout.addWidget(SpeakerCommands(self._service, self._jobs, device, body))
        from app.core.router import is_router
        if is_router(device):
            from app.ui.router_panel import RouterPanel
            layout.addWidget(RouterPanel(self._service, self._jobs, device, body))
        from app.ui.workbench_panel import WorkbenchPanel
        panel = WorkbenchPanel(self._service, self._jobs, body)
        panel.setMinimumHeight(360)
        layout.addWidget(panel, 1)
        previous = self._detail_scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self._detail_scroll.setWidget(body)
        self._stack.setCurrentWidget(self._detail_page)
        panel.show_device(device.did, online=device.online, device=device)

    def _voice_transcript(self, text: str) -> None:
        self._voice_edit.setText(text)
        self._emit_voice()

    def _voice_status(self, message: str) -> None:
        self._typewriter.stop()
        self._voice_edit.setPlaceholderText(message)

    def _emit_voice(self) -> None:
        text = self._voice_edit.text().strip()
        if not text:
            return
        speaker = self._pick_speaker()
        if speaker is None:
            return
        # 设置的默认音箱不在线/不在列表 → 已回退：提示里说明，并把
        # 设置回退为「自动」（否则偏好一直指向离线设备，每次都要回退）
        pref = settings_store.get_default_speaker_did()
        fallback_note = ""
        if pref and pref != speaker.did:
            fallback_note = f"（首选音箱离线，已由「{speaker.name}」代答）"
            settings_store.set_default_speaker_did("")
        self._voice_edit.clear()
        self._jobs.submit(
            lambda: self._service.run_action(speaker.did, "execute-text-directive", [text]),
            on_success=lambda _, note=fallback_note: self._on_voice_success(text, note),
            on_error=lambda e: self._on_voice_error(e),
        )

    def _on_voice_success(self, text: str, fallback_note: str = "") -> None:
        from app.ui.toast import Toast
        self._voice_edit.setPlaceholderText(f"已发送：{text}")
        self._voice_edit.setToolTip(f"已告诉小爱同学：{text}{fallback_note}")
        Toast.info(self, f"已告诉小爱同学：{text}{fallback_note}", 3000)

    def _on_voice_error(self, err: Exception) -> None:
        from app.ui.toast import Toast
        self._voice_edit.setPlaceholderText("执行失败，可修改指令后重试")
        Toast.info(self, f"执行失败：{err}", 4000)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is getattr(self, "_voice_edit", None) and event.type() == event.Type.KeyPress and event.key() == Qt.Key_Escape:
            self._voice_edit.clear()
            return True
        if not self.isVisible():
            return super().eventFilter(obj, event)
        # 只监听失活事件（点击托盘图标、切到其他应用/桌面），不监听全局
        # MouseButtonPress——点击托盘图标本身就是窗口外点击，若用 MouseButtonPress
        # 判断窗口外会与呼出竞态，造成"开了又关/闪烁"
        et = event.type()
        if et in (QEvent.WindowDeactivate, QEvent.ApplicationDeactivate):
            # 呼出动画期间不隐藏，等动画完成再评估
            if self._show_anim is not None:
                return super().eventFilter(obj, event)
            if not self.underMouse():
                QTimer.singleShot(80, self._maybe_hide_on_deactivate)
            return super().eventFilter(obj, event)
        return super().eventFilter(obj, event)

    def _maybe_hide_on_deactivate(self) -> None:
        import shiboken6

        if not shiboken6.isValid(self) or not self.isVisible() or self._show_anim is not None:
            return
        if self._mic.is_listening():
            return
        # 只有真正失活且鼠标不在托盘窗口内才隐藏
        if self.isActiveWindow() or self.underMouse():
            return
        # 若当前激活窗口是本应用的其他窗口（主窗口/管理对话框/设备详情），
        # 则不应隐藏托盘——用户只是切到了我方另一个窗口
        from PySide6.QtWidgets import QApplication
        active = QApplication.activeWindow()
        if QApplication.activePopupWidget() is not None:
            return
        if active is not None and active is not self:
            # 管理对话框/详情是顶层窗口，主窗口也可能是，需判断是否同属本应用
            top = active.window()
            if top is not None and top is not self:
                return
        self.hide_animated()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_glass(self)
        # 延迟安装，避免托盘那一下 MouseButtonPress 立刻又触发隐藏
        QTimer.singleShot(120, self._install_outside_filter)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._control_timer.stop()
        self._mic.cancel()
        if self._size_timer.isActive():
            self._size_timer.stop()
            settings_store.set_tray_size(self.width(), self.height())
        self._end_tray_edits()
        self._tray_visible = False
        self._typewriter.stop()
        self._remove_outside_filter()
        super().hideEvent(event)

    def _refresh_controls(self) -> None:
        self._registry.refresh(self._tray_dids)

    def _install_outside_filter(self) -> None:
        import shiboken6

        if not shiboken6.isValid(self) or self._outside_filter_installed:
            return
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._outside_filter_installed = True

    def _remove_outside_filter(self) -> None:
        if not self._outside_filter_installed:
            return
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        self._outside_filter_installed = False

    def refresh_power(self, dids: list[str]) -> None:
        if not dids:
            return
        self._jobs.submit(
            lambda: self._service.power_states(dids),
            on_success=self._apply_power,
            on_error=lambda _: None,
        )

    def _apply_power(self, states: dict[str, bool | None]) -> None:
        import shiboken6

        if not shiboken6.isValid(self):
            return
        for did, st in states.items():
            self._known_power[did] = st
        # 遍历 QGridLayout 直接子项
        grid = getattr(self, "_grid", None)
        if grid is None:
            return
        for did, st in states.items():
            for i in range(grid.count()):
                w = grid.itemAt(i).widget()
                if w is not None and getattr(w, "_did", None) == did:
                    btn = getattr(w, "_power_btn", None)
                    if btn is not None:
                        btn.set_state(st)
                    break

    def _rebuild(self) -> None:
        self._destroy_grid()
        dids = getattr(self, "_tray_dids", None)
        if dids is None:
            dids = self._tray_dids = tray_store.load()
        scene_data = getattr(self, "_tray_scenes", None)
        if scene_data is None:
            scene_data = self._tray_scenes = tray_store.load_scenes()
        order = getattr(self, "_tray_order", None)
        if order is None:
            order = self._tray_order = tray_store.load_order()
        lookup = {d.did: d for d in self._devices}
        has_controls = any(d in lookup and supports_quick_controls(lookup[d]) for d in dids)
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        self._sync_tray_height()
        did_set = set(dids)
        scene_map = {s["scene_id"]: SceneInfo(**s) for s in scene_data}
        # 设备与场景按统一排序混排；不在 order 里的（异常文件兜底）追加末尾
        rows: list[QFrame] = []
        seen: set[tuple[str, str]] = set()
        for item in order:
            t, i = item["type"], item["id"]
            if t == "device" and i in did_set and lookup.get(i) is not None:
                rows.append(self._make_row(lookup[i]))
            elif t == "scene" and i in scene_map:
                rows.append(self._make_scene_row(scene_map[i]))
            else:
                continue
            seen.add((t, i))
        for d in dids:
            if ("device", d) not in seen and lookup.get(d) is not None:
                rows.append(self._make_row(lookup[d]))
                seen.add(("device", d))
        for s in scene_data:
            sid = s["scene_id"]
            if ("scene", sid) not in seen:
                rows.append(self._make_scene_row(scene_map[sid]))
                seen.add(("scene", sid))
        if not rows:
            self._empty.show()
            self._scroll.hide()
            return
        self._empty.hide()
        self._scroll.show()
        # 使用 QGridLayout + setColumnStretch 强制各列等宽，单卡也能保持列宽
        cols = self._effective_columns()
        self._layout_columns = cols
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        for idx, row in enumerate(rows):
            kind = "device" if hasattr(row, "_did") else "scene"
            ident = row._did if kind == "device" else row._scene_id
            wrapper = self._sorter.wrap_card(f"{kind}:{ident}", row)
            wrapper._did = getattr(row, "_did", None)
            wrapper._power_btn = getattr(row, "_power_btn", None)
            self._grid.addWidget(wrapper, idx // cols, idx % cols)
        self._sorter.set_enabled(self._sort_mode)
        self._list_lay.addLayout(self._grid)
        self._list_lay.addStretch(1)
        online_dids = [d for d in dids if lookup.get(d) and lookup[d].online and self._known_power.get(d) is None]
        if online_dids:
            self.refresh_power(online_dids)

    def _destroy_grid(self) -> None:
        self._end_tray_edits()
        self._sorter.clear()
        grid = getattr(self, "_grid", None)
        if grid is None:
            return
        # 移除 _list_lay 中的 grid 布局项
        for i in range(self._list_lay.count()):
            item = self._list_lay.itemAt(i)
            if item and item.layout() is grid:
                self._list_lay.takeAt(i)
                break
        # 清理 grid 中的 widget
        while grid.count():
            it = grid.takeAt(0)
            if w := it.widget():
                if isinstance(w, QuickDeviceCard):
                    w.session.editing = False
                w.deleteLater()
        grid.deleteLater()
        self._grid = None
        self._sub_labels.clear()
        self._sub_widths.clear()
        # 移除多余的 stretch
        for i in range(self._list_lay.count() - 1, -1, -1):
            item = self._list_lay.itemAt(i)
            if item and item.spacerItem():
                self._list_lay.takeAt(i)
                break

    def _end_tray_edits(self) -> None:
        from PySide6.QtWidgets import QSlider
        for card in self._host.findChildren(QuickDeviceCard):
            for _, control, _ in card._controls.values():
                if isinstance(control, QSlider) and control.isSliderDown():
                    control.setSliderDown(False)
                    card.session.editing = False

    def _card_text_width(self, has_power: bool) -> int:
        """卡片文本列的可用宽度（窗口宽固定，各边距确定，可直接算出）。

        卡片内文本不省略时 QLabel 最小宽取整段文本，温湿度+开关会把
        列宽撑爆、整个网格溢出面板；所有文本都按此宽度省略兜底。
        """
        # 根面板左右边距 28 + 列表右边距 6 + 列间距 6×(cols-1)
        columns = self._effective_columns()
        inner = self.width() - 40 - 6 * (columns - 1)
        col = inner / columns
        # 卡片左右边距 24 + 文本列与开关间距 10 + 开关按钮 28
        return max(36, round(col - 24 - 10 - (28 if has_power else 0)))

    @staticmethod
    def _set_elided(label: QLabel, text: str, width: int | None) -> None:
        """按可用宽度省略显示文本，完整内容放 tooltip。"""
        if width is None:
            label.setText(text)
        else:
            label.setText(label.fontMetrics().elidedText(
                text, Qt.ElideRight, width))
        label.setToolTip(text)

    def _make_row(self, dev: DeviceInfo) -> QFrame:
        if supports_quick_controls(dev):
            card = QuickDeviceCard(self._registry.session(dev))
            card.open_details.connect(self._open_inline)
            return card
        row = QFrame()
        row.setObjectName("trayRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setFixedHeight(56)
        from PySide6.QtWidgets import QSizePolicy
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setStyleSheet(
            f"QFrame#trayRow {{ background: {SiColors.CARD}; border: 1px solid {SiColors.LINE}; border-radius: 10px; }}"
            f"QFrame#trayRow:hover {{ background: {SiColors.CARD_HOVER}; border-color: {SiColors.CARD_BORDER_HOVER}; }}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        symbol = 'mdi.speaker' if is_speaker(dev) else 'mdi.router-wireless' if '.router.' in dev.model else 'mdi.devices'
        icon = QLabel()
        icon.setPixmap(qta.icon(symbol, color=SiColors.THEME if dev.online else SiColors.ICON_DIM).pixmap(24, 24))
        lay.addWidget(icon)

        known = self._known_power.get(dev.did)
        avail = self._card_text_width(known is not None)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel()
        name.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {SiColors.TEXT_PRIMARY if dev.online else f'{SiColors.OFFLINE_TEXT}'}; background: transparent;")
        # 水平 Ignored：布局可无限压缩标签，文本绝不可能把列撑宽
        # （setMinimumWidth(0) 无效——qSmartMinSize 只认 >0 的显式最小宽）
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._set_elided(name, dev.name, avail)
        # 副标题：在线仅显示房间（+温湿度），离线才追加“· 离线”
        metrics = self._metrics.get(dev.did)
        if dev.online:
            sub_text = f"{dev.room_name} | {metrics}" if metrics else dev.room_name
        else:
            sub_text = f"{dev.room_name} · 离线"
        sub = QLabel()
        # setFont 提供与渲染一致的 fontMetrics；但应用级 QSS `*{font-size:10pt}`
        # 会盖掉 setFont，故样式表里也要写 8pt，两者缺一度量与渲染就不一致
        sub.setFont(QFont("Microsoft YaHei UI", 8))
        sub.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY if dev.online else f'{SiColors.OFFLINE_SUB}'}; background: transparent; font-size: 8pt;")
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._set_elided(sub, sub_text, avail)
        self._sub_labels[dev.did] = sub
        self._sub_widths[dev.did] = avail
        text_col.addWidget(name)
        text_col.addWidget(sub)
        lay.addLayout(text_col, stretch=1)

        btn = None
        if known is not None:
            btn = PowerButton(28, icon_size=22)
            btn.set_online(dev.online)
            btn.set_state(known)
            def _on_toggle(checked=False, d=dev.did, b=btn):
                b.set_busy(True)
                self._jobs.submit(
                    lambda: self._service.toggle_power(d),
                    on_success=lambda ns, dd=d, bb=b: self._on_toggle_done(dd, ns, bb),
                    on_error=lambda e, bb=b: self._on_toggle_error(bb, e),
                )
            btn.clicked.connect(_on_toggle)
            lay.addWidget(btn)
        row._did = dev.did  # type: ignore[attr-defined]
        row._power_btn = btn  # type: ignore[attr-defined]

        row.mousePressEvent = lambda e, d=dev.did: self._open_inline(d) if e.button() == Qt.LeftButton else None
        row.setCursor(Qt.PointingHandCursor)
        return row

    def _on_toggle_done(self, did: str, ns: bool, btn) -> None:
        self._known_power[did] = ns
        import shiboken6
        if shiboken6.isValid(btn):
            btn.set_state(ns)
            btn.set_busy(False)

    def _on_toggle_error(self, btn, error) -> None:
        import shiboken6
        if shiboken6.isValid(btn):
            btn.set_busy(False)
        Toast.info(self, f"操作未确认：{error}", 4000)

    # ---------- 场景行 ----------

    def _make_scene_row(self, scene: SceneInfo) -> QFrame:
        row = QFrame()
        row.setObjectName("trayRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setFixedHeight(56)
        from PySide6.QtWidgets import QSizePolicy
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setStyleSheet(
            f"QFrame#trayRow {{ background: {SiColors.CARD}; border: 1px solid {SiColors.LINE}; border-radius: 10px; }}"
            f"QFrame#trayRow:hover {{ background: {SiColors.CARD_HOVER}; border-color: {SiColors.CARD_BORDER_HOVER}; }}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        avail = self._card_text_width(True)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel()
        name.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {SiColors.TEXT_PRIMARY}; background: transparent;")
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._set_elided(name, scene.name, avail)
        sub = QLabel()
        sub.setFont(QFont("Microsoft YaHei UI", 8))
        sub.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; background: transparent; font-size: 8pt;")
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._set_elided(sub, scene.home_name or "手动场景", avail)
        text_col.addWidget(name)
        text_col.addWidget(sub)
        lay.addLayout(text_col, stretch=1)

        btn = QPushButton()
        btn.setObjectName("sceneRunBtn")
        btn.setFixedSize(28, 28)
        btn.setIconSize(QSize(18, 18))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("执行场景")
        self._apply_scene_btn(btn, busy=False)
        btn.clicked.connect(lambda _, s=scene, b=btn: self._run_scene(s, b))
        lay.addWidget(btn)
        row._scene_id = scene.scene_id  # type: ignore[attr-defined]
        return row

    def _apply_scene_btn(self, btn: QPushButton, busy: bool) -> None:
        btn.setEnabled(not busy)
        if busy:
            btn.setIcon(qta.icon('mdi.play', color=SiColors.ICON_DIM))
            btn.setStyleSheet(
                f"QPushButton#sceneRunBtn {{ background: {SiColors.SURFACE_PRESSED};"
                f" border: none; border-radius: 14px; }}")
            return
        btn.setIcon(qta.icon('mdi.play', color=SiColors.WHITE))
        btn.setStyleSheet(
            f"QPushButton#sceneRunBtn {{ background: {SiColors.THEME}; border: none;"
            f" border-radius: 14px; }}"
            f"QPushButton#sceneRunBtn:hover {{ background: {SiColors.THEME_HOVER}; }}"
            f"QPushButton#sceneRunBtn:pressed {{ background: {SiColors.THEME_DIM}; }}")

    def _run_scene(self, scene: SceneInfo, btn: QPushButton) -> None:
        # 与主界面场景卡一致：点击即执行（无二次确认），执行中置忙碌态
        self._apply_scene_btn(btn, busy=True)
        self._jobs.submit(
            lambda: self._service.run_scene(scene),
            on_success=lambda _, s=scene, b=btn: self._on_scene_done(s, b),
            on_error=lambda e, s=scene, b=btn: self._on_scene_failed(s, b, e),
        )

    def _on_scene_done(self, scene: SceneInfo, btn: QPushButton) -> None:
        import shiboken6

        if not shiboken6.isValid(self) or not shiboken6.isValid(btn):
            return
        self._apply_scene_btn(btn, busy=False)
        Toast.info(self, f"已执行场景「{scene.name}」", 2200)

    def _on_scene_failed(self, scene: SceneInfo, btn: QPushButton, error: Exception) -> None:
        import shiboken6

        if not shiboken6.isValid(self) or not shiboken6.isValid(btn):
            return
        self._apply_scene_btn(btn, busy=False)
        Toast.info(self, f"执行场景「{scene.name}」失败：{error}", 4000)

    def show_near_tray(self) -> None:
        """在托盘附近或屏幕右下角显示，显示前重建以保证与托盘存储一致。"""
        self._tray_dids = tray_store.load()
        self._tray_scenes = tray_store.load_scenes()
        self._tray_order = tray_store.load_order()
        self._back_to_devices()
        self._rebuild()
        self.presence_requested.emit()
        self._refresh_controls()
        self._control_timer.start()
        # 顶部音频栏与语音输入条显隐需在计算弹出位置前确定，以便窗口高度正确
        self._update_audio_bar()
        self._update_voice_bar()
        # 托盘内的温湿度设备在显示时补拉一次读数，确保副标题及时带上温湿度
        try:
            dids = [d for d in self._tray_dids if self._metrics.get(d) is None]
            if dids:
                self._jobs.submit(
                    lambda: self._service.read_metrics(dids),
                    on_success=lambda m: self.set_metrics({**self._metrics, **{k: v for k, v in m.items() if v}}),  # noqa: E501
                    on_error=lambda _: None,
                )
        except Exception:
            pass
        # 先显示并同步高度，再计算弹出位置，避免首帧用未校正高度导致压住任务栏
        self._play_show_animation()

    def _play_show_animation(self) -> None:
        # 若正在隐藏，先停掉
        if self._hide_anim is not None:
            try:
                self._hide_anim.stop()  # 中途停止不发 finished，须手动清理
            except Exception:
                pass
            self._hide_anim.deleteLater()
            self._hide_anim = None
        if self._show_anim is not None:
            try:
                self._show_anim.stop()
            except Exception:
                pass
            self._show_anim.deleteLater()
            self._show_anim = None
        # 呼出前先同步高度（隐藏态确定性计算），保证窗口尺寸在显示前即正确，
        # 避免显示后再 resize 造成闪烁
        self._sync_tray_height()
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            target = self.pos()
        else:
            geo = screen.availableGeometry()
            x = geo.right() - self.width() - 16
            y = geo.bottom() - self.height() - 16
            target = QPoint(max(geo.left(), x), max(geo.top(), y))
        self._target_pos = target
        # 动画起点：目标下方 10px + 透明 0，全部在隐藏态摆好，只 show 一次
        start = QPoint(target.x(), target.y() + 10)
        self.move(start)
        self.setWindowOpacity(1.0)
        self._tray_visible = True
        self.show()
        self.raise_()
        self.activateWindow()
        group = QParallelAnimationGroup(self)
        pos_anim = QPropertyAnimation(self, b"pos", group)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(target)
        pos_anim.setDuration(220)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        op_anim = QPropertyAnimation(self, b"windowOpacity", group)
        op_anim.setStartValue(0.0)
        op_anim.setEndValue(1.0)
        op_anim.setDuration(200)
        op_anim.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(pos_anim)
        if not glass_supported():
            group.addAnimation(op_anim)
        self._show_anim = group
        # 自然结束时清理；被打断的组在各 stop 处手动 deleteLater，
        # 否则旧组随每次显隐在窗口下不断堆积
        group.finished.connect(lambda: (
            setattr(self, "_show_anim", None),
            group.deleteLater(),
        ))
        group.start()

    def hide_animated(self) -> None:
        """带动画隐藏；已隐藏或正隐藏则直接返回。"""
        if not self.isVisible():
            return
        if self._hide_anim is not None:
            return
        if self._show_anim is not None:
            try:
                self._show_anim.stop()  # 中途停止不发 finished，须手动清理
            except Exception:
                pass
            self._show_anim.deleteLater()
            self._show_anim = None
        start = self.pos()
        end = QPoint(start.x(), start.y() + 10)
        group = QParallelAnimationGroup(self)
        pos_anim = QPropertyAnimation(self, b"pos", group)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.setDuration(160)
        pos_anim.setEasingCurve(QEasingCurve.InCubic)
        op_anim = QPropertyAnimation(self, b"windowOpacity", group)
        op_anim.setStartValue(self.windowOpacity() if self.windowOpacity() > 0 else 1.0)
        op_anim.setEndValue(0.0)
        op_anim.setDuration(160)
        op_anim.setEasingCurve(QEasingCurve.InCubic)
        group.addAnimation(pos_anim)
        if not glass_supported():
            group.addAnimation(op_anim)

        def _on_finished():
            self._hide_anim = None
            group.deleteLater()
            self.setWindowOpacity(1.0)
            # 避免递归触发 hideEvent 中的动画
            self.hide()

        group.finished.connect(_on_finished)
        self._hide_anim = group
        group.start()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        QTimer.singleShot(150, self._maybe_hide)

    def _maybe_hide(self) -> None:
        import shiboken6

        if not shiboken6.isValid(self):
            return
        # 失焦触发：与 deactivate 同一套排除逻辑，避免管理对话框/详情
        # 等本应用窗口打开时误隐藏托盘
        if self._show_anim is not None or self.isActiveWindow() or self.underMouse():
            return
        if self._mic.is_listening():
            return
        from PySide6.QtWidgets import QApplication
        active = QApplication.activeWindow()
        if QApplication.activePopupWidget() is not None:
            return
        if active is not None and active is not self:
            top = active.window()
            if top is not None and top is not self:
                return
        self.hide_animated()




