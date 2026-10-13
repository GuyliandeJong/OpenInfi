"""Colours and the Qt style sheet of the configurator."""

BG = "#141519"
SIDEBAR = "#1a1b20"
SURFACE = "#1f2127"
SURFACE_2 = "#272a31"
SURFACE_3 = "#30333b"
BORDER = "#363a43"
TEXT = "#e9eaee"
MUTED = "#9a9eaa"
FAINT = "#6b707c"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#7aa2ff"
SUCCESS = "#3fb950"
WARNING = "#e3a008"
DANGER = "#f85149"

STYLE = f"""
* {{ color: {TEXT}; font-size: 10pt; }}
QMainWindow, #Page {{ background: {BG}; }}
#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#Brand {{ font-size: 15pt; font-weight: 700; }}
#BrandSub {{ color: {MUTED}; font-size: 9pt; }}
#Nav {{ background: transparent; border: none; outline: none; }}
#Nav::item {{ padding: 10px 14px; margin: 2px 8px; border-radius: 8px; color: {MUTED}; }}
#Nav::item:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
#Nav::item:selected {{ background: {SURFACE_3}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}
#PageTitle {{ font-size: 17pt; font-weight: 700; }}
#PageSubtitle {{ color: {MUTED}; }}
#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#CardTitle {{ font-size: 11pt; font-weight: 600; }}
#Muted, QLabel[muted="true"] {{ color: {MUTED}; }}
#Faint {{ color: {FAINT}; font-size: 9pt; }}
#Section {{ color: {MUTED}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }}
QPushButton {{
    background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: #3a3e47; }}
QPushButton:pressed {{ background: #2b2e35; }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE_2}; border-color: {SURFACE_3}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[primary="true"]:disabled {{ background: {SURFACE_3}; border-color: {SURFACE_3}; color: {FAINT}; }}
QPushButton[danger="true"] {{ color: {DANGER}; }}
QPushButton[flat="true"] {{ background: transparent; border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton[flat="true"]:hover {{ color: {TEXT}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton:checked:disabled {{ background: {SURFACE_3}; border-color: {BORDER}; color: {FAINT}; }}
#EffectTile {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px;
    text-align: left; padding: 10px 12px;
}}
#EffectTile:hover {{ border-color: #4a4f5a; background: #2c2f37; }}
#EffectTile:checked {{ border: 2px solid {ACCENT}; background: #232a3b; color: {TEXT}; }}
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: white; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
}}
QSlider::handle:horizontal:disabled {{ background: {FAINT}; }}
QSlider::sub-page:horizontal:disabled {{ background: {SURFACE_3}; }}
QLineEdit, QComboBox, QPlainTextEdit, QListWidget {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QListWidget::item {{ padding: 5px 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
QListWidget::item:hover:!selected {{ background: {SURFACE_3}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: {SURFACE_3}; border: 1px solid {BORDER}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{ background: {SURFACE_3}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
#Toast {{ background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px 16px; }}
#Toast[kind="ok"] {{ border-left: 4px solid {SUCCESS}; }}
#Toast[kind="error"] {{ border-left: 4px solid {DANGER}; }}
#Toast[kind="busy"] {{ border-left: 4px solid {ACCENT}; }}
#Banner {{ background: #3a2f12; border: 1px solid #5c4a17; border-radius: 10px; padding: 10px 14px; }}
#Banner[kind="error"] {{ background: #3d1d1d; border-color: #6b2c2c; }}
#Chip {{ background: {SURFACE_3}; border-radius: 10px; padding: 3px 10px; color: {MUTED}; font-size: 9pt; }}
"""
