# -*- coding: utf-8 -*-

# Copyright (C) 2026 Kobayashi Land and House Investigator Office
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""
dialog.py  ―  MOJ任意座標変換ローダー  図郭別GCP/変換パラメータ対応版

【レイアウト】
  左(固定320px): ファイル選択 → 情報 → 住所選択 → 表示ボタン → 統計
  右上:           プレビューキャンバス（ズーム/パン、筆界点クリックでGCP登録）
  右下:           図郭選択タブ（図郭ごとに独立したGCPテーブル＋変換設定）

  ★ 図郭タブを切り替えるとキャンバスの強調表示が切り替わる
  ★ 各図郭は独立した変換パラメータを持つ
  ★ ウィンドウ最小サイズ 1400×900

【座標系の扱い】
  parser.points: (disp_x=東西, disp_y=南北)  ← XML X,Y をswapした表示座標
  transform_func(disp_x, disp_y) → (plane_X=北, plane_Y=東)   ← ユーザーがGCPで指定
  QgsPointXY(plane_Y, plane_X)   ← QGISはx=東, y=北
"""

import os

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QFileDialog,
    QMessageBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QGraphicsScene, QGraphicsView,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsSimpleTextItem,
    QApplication, QFrame, QSplitter, QTabWidget,
    QRadioButton, QButtonGroup, QHeaderView,
    QGraphicsItem, QToolTip, QSizePolicy, QScrollArea
)
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import (
    QColor, QPen, QBrush, QPolygonF, QFont, QPainter, QCursor
)

try:
    from qgis.core import (
        QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
        QgsField, QgsProject, QgsCoordinateReferenceSystem,
        QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
        QgsTextFormat
    )
    from qgis.gui import QgsProjectionSelectionWidget
    from qgis.PyQt.QtCore import QVariant
    # QGIS 3.36+ では QgsField(name, QVariant.String) が非推奨になり
    # QgsField(name, QMetaType.Type.QString) が推奨される。
    # 両バージョンに対応するため互換ラッパーを用意する。
    try:
        from qgis.PyQt.QtCore import QMetaType
        _STR_TYPE = QMetaType.Type.QString
    except (ImportError, AttributeError):
        _STR_TYPE = QVariant.String
    QGIS_AVAILABLE = True
    QGIS_CRS_WIDGET = True
except ImportError:
    QGIS_AVAILABLE = False
    QGIS_CRS_WIDGET = False
    _STR_TYPE = None

from .xml_parser import MOJXMLParser
from .coordinate_transform import auto_transform, format_params


# ============================================================
# カラー定数
# ============================================================
C_BG       = '#f4f6fb'
C_PANEL    = '#ffffff'
C_BORDER   = '#2c3e6e'
C_HDR_BG   = '#2c3e6e'
C_HDR_FG   = '#ffffff'
C_TEXT     = '#1a1a2e'
C_TEXT_SUB = '#505878'
C_ACCENT   = '#1a6b3c'
C_WARN     = '#b5451b'
C_INFO_BG  = '#eaeff8'
C_INFO_BD  = '#8898bc'
C_CANVAS   = '#1e2533'

# 図郭ごとの配色（最大8図郭対応、それ以上は循環）
# (アクティブ輪郭色, アクティブ塗り, 非アクティブ塗り, 点色)
ZG_PALETTE = [
    ('#e07800', (255, 165,   0, 110), (200, 130,   0,  30), '#ffaa00'),
    ('#0060d0', ( 50, 120, 220, 110), ( 50, 100, 180,  30), '#44aaff'),
    ('#00a040', (  0, 160,  64, 110), (  0, 130,  50,  30), '#44ff88'),
    ('#c000b0', (180,   0, 160, 110), (140,   0, 120,  30), '#ff44dd'),
    ('#a04000', (160,  64,   0, 110), (120,  50,   0,  30), '#ff8844'),
    ('#007880', (  0, 120, 128, 110), (  0,  90, 100,  30), '#44ddee'),
    ('#604080', ( 96,  64, 128, 110), ( 70,  50, 100,  30), '#aa88dd'),
    ('#806000', (128,  96,   0, 110), (100,  75,   0,  30), '#ddbb00'),
]

_STYLE = f"""
QDialog {{
    background-color: {C_BG};
    font-family: 'Meiryo UI', 'Yu Gothic UI', 'MS UI Gothic', sans-serif;
    font-size: 9pt;
    color: {C_TEXT};
}}
QGroupBox {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-radius: 5px;
    margin-top: 16px;
    padding-top: 4px;
    font-weight: bold;
    color: {C_TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px; top: -1px;
    padding: 2px 8px;
    background-color: {C_HDR_BG};
    color: {C_HDR_FG};
    border-radius: 3px;
}}
QTabWidget::pane {{
    border: 1px solid {C_BORDER};
    border-top: none;
    background: {C_PANEL};
}}
QTabBar::tab {{
    background: #d4dae8;
    color: {C_TEXT};
    font-weight: bold;
    padding: 5px 14px;
    margin-right: 2px;
    border: 1px solid {C_BORDER};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 120px;
}}
QTabBar::tab:selected {{
    background: {C_HDR_BG};
    color: {C_HDR_FG};
}}
QTabBar::tab:hover:!selected {{ background: #b8c4dc; }}
QPushButton {{
    background-color: {C_BORDER};
    color: {C_HDR_FG};
    border: none; border-radius: 4px;
    padding: 5px 12px; font-weight: bold; font-size: 9pt; min-height: 24px;
}}
QPushButton:hover {{ background-color: #3d5498; }}
QPushButton:pressed {{ background-color: #1a2a50; }}
QPushButton:disabled {{ background-color: #b0b8cc; color: #e0e4ec; }}
QPushButton#btn_exec_zg {{
    background-color: {C_WARN}; color: #fff;
    font-size: 9pt; padding: 5px 14px; min-height: 26px;
}}
QPushButton#btn_exec_zg:hover {{ background-color: #d4561f; }}
QPushButton#btn_exec_zg:disabled {{ background-color: #c8a090; color: #f0e8e4; }}
QPushButton#btn_add_layer {{
    background-color: {C_ACCENT}; color: #fff;
    font-size: 10pt; padding: 6px 16px; min-height: 28px;
}}
QPushButton#btn_add_layer:hover {{ background-color: #228b4e; }}
QPushButton#btn_add_layer:disabled {{ background-color: #90b8a0; color: #e0ede6; }}
QPushButton#btn_export {{
    background-color: #4a5a8c; color: #fff;
    font-size: 10pt; padding: 6px 16px; min-height: 28px;
}}
QPushButton#btn_export:hover {{ background-color: #5a6aaa; }}
QPushButton#btn_export:disabled {{ background-color: #a0a8c0; color: #e0e4ec; }}
QLabel {{ color: {C_TEXT}; font-size: 9pt; }}
QLabel#lbl_title {{
    background-color: {C_HDR_BG}; color: {C_HDR_FG};
    border-radius: 5px; padding: 8px 14px; font-weight: bold; font-size: 11pt;
}}
QLabel#lbl_canvas_hint {{
    background-color: {C_HDR_BG}; color: {C_HDR_FG};
    border-radius: 3px; padding: 4px 10px; font-size: 8pt;
}}
QLabel#lbl_stat {{
    background-color: {C_INFO_BG}; color: {C_TEXT};
    border: 1px solid {C_INFO_BD}; border-radius: 4px;
    padding: 4px 8px; font-size: 8pt;
}}
QLabel#lbl_result {{
    background-color: {C_INFO_BG}; color: {C_TEXT};
    border: 1px solid {C_INFO_BD}; border-radius: 4px;
    padding: 5px 8px; font-family: 'Courier New', monospace; font-size: 8pt;
}}
QLabel#lbl_sub {{ color: {C_TEXT_SUB}; font-size: 8pt; }}
QLabel#lbl_no_koaza {{ color: {C_TEXT_SUB}; font-size: 8pt; font-style: italic; }}
QLabel#lbl_crs_shared {{
    background-color: {C_INFO_BG}; color: {C_TEXT_SUB};
    border: 1px solid {C_INFO_BD}; border-radius: 3px;
    padding: 3px 8px; font-size: 8pt;
}}
QLineEdit {{
    border: 1px solid {C_BORDER}; border-radius: 3px;
    padding: 3px 6px; background: {C_PANEL}; color: {C_TEXT}; font-size: 9pt;
}}
QLineEdit:read-only {{ background: #edf0f7; color: {C_TEXT_SUB}; }}
QComboBox {{
    border: 1px solid {C_BORDER}; border-radius: 3px;
    padding: 3px 6px; background: {C_PANEL}; color: {C_TEXT};
    font-size: 9pt; min-height: 22px;
}}
QComboBox:disabled {{ background: #edf0f7; color: #909090; }}
QComboBox QAbstractItemView {{
    color: {C_TEXT}; background: white;
    selection-background-color: {C_BORDER}; selection-color: white;
}}
QListWidget {{
    border: 1px solid {C_BORDER}; border-radius: 3px;
    background: {C_PANEL}; color: {C_TEXT};
    alternate-background-color: #eef2f9; font-size: 9pt;
}}
QListWidget::item:selected {{ background-color: {C_BORDER}; color: white; }}
QListWidget::item:hover {{ background-color: #d8e0f0; }}
QTableWidget {{
    border: 1px solid {C_BORDER}; gridline-color: #c8d0e0;
    background: white; color: {C_TEXT};
    font-size: 9pt; alternate-background-color: #eef2f9;
}}
QTableWidget::item:selected {{ background-color: {C_BORDER}; color: white; }}
QHeaderView::section {{
    background-color: {C_HDR_BG}; color: {C_HDR_FG};
    font-weight: bold; padding: 5px 6px;
    border: none; border-right: 1px solid #4a5a8c; font-size: 9pt;
}}
QRadioButton {{ color: {C_TEXT}; font-size: 9pt; spacing: 5px; }}
QSplitter::handle:horizontal {{ width: 3px; background: {C_BORDER}; }}
QSplitter::handle:vertical {{ height: 3px; background: {C_BORDER}; }}
"""

_LABEL_FONT_SIZE = 9
_PT_RADIUS = 5
_PT_RADIUS_GCP = 7


# ============================================================
# 図郭状態クラス（図郭ごとのGCP・変換パラメータを保持）
# ============================================================

class ZukakuState:
    """1図郭分の状態・UIウィジェット参照をまとめたクラス"""

    def __init__(self, zg_dict, fude_list, palette_idx):
        self.zg = zg_dict
        self.fude_list = fude_list
        self.fude_ids = {f['id'] for f in fude_list}
        self.map_no = zg_dict.get('地図番号', '?')
        pal = ZG_PALETTE[palette_idx % len(ZG_PALETTE)]
        self.stroke_active   = pal[0]
        self.fill_active     = pal[1]
        self.fill_inactive   = pal[2]
        self.point_color     = pal[3]

        # GCP / 変換状態
        self.selected_gcps = []        # [(pid, disp_x, disp_y)]
        self.transform_func = None
        self.params_text = ''

        # UIウィジェット（_build_zg_tab()で設定）
        self.gcp_table = None          # GCPTableWidget
        self.lbl_result = None         # QLabel
        self.radio_auto = None
        self.radio_helmert = None
        self.radio_affine = None
        self.btn_exec_zg = None

        # グラフィックアイテム（_draw_polygons()で設定）
        self.poly_items = {}           # fude_id -> QGraphicsPolygonItem
        self.point_items = {}          # pid -> FixedPointItem
        self.bbox = (0.0, 1.0, 0.0, 1.0)  # (x_lo, x_hi, y_lo, y_hi) 実座標


# ============================================================
# グラフィックアイテム（ズーム固定サイズ）
# ============================================================

class FixedPointItem(QGraphicsEllipseItem):
    """ItemIgnoresTransformations で常にスクリーン固定サイズの筆界点"""

    def __init__(self, scene_x, scene_y, point_id, parent_dialog,
                 radius=5, color=None):
        r = float(radius)
        super().__init__(-r, -r, r * 2, r * 2)
        self.point_id = point_id
        self.parent_dialog = parent_dialog
        self._scene_x = scene_x
        self._scene_y = scene_y
        self._radius = r              # mark_as_gcp 内で参照するため必須
        self._normal_color = color or '#00aaff'
        self._is_gcp = False

        self._label_item = None   # GCP登録時に表示する点番ラベル

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setPos(scene_x, scene_y)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip(f"筆界点: {point_id}\nクリックでGCP登録")
        self._refresh()

    def _refresh(self):
        if self._is_gcp:
            self.setBrush(QBrush(QColor('#ff3300')))
            self.setPen(QPen(QColor('#ffffff'), 1.5))
            self.setZValue(20)
        else:
            self.setBrush(QBrush(QColor(self._normal_color)))
            self.setPen(QPen(QColor('#003050'), 0.8))
            self.setZValue(10)

    def mark_as_gcp(self, flag=True):
        self._is_gcp = flag
        self._refresh()
        scene = self.scene()
        if flag:
            # 点番ラベルをキャンバスに追加（右上オフセット）
            if self._label_item is None:
                # 親アイテム(self)の子として配置することで
                # 座標がスクリーンピクセル固定になる
                lbl = QGraphicsSimpleTextItem(str(self.point_id), self)
                f = QFont("Meiryo UI")
                f.setPointSize(8)
                f.setBold(True)
                lbl.setFont(f)
                lbl.setBrush(QBrush(QColor('#ffffff')))
                self._label_item = lbl  # setPos前に代入 → 例外発生時もクリーンアップ可能
                lbl.setPos(self._radius + 1, -lbl.boundingRect().height() / 2)
                lbl.setZValue(25)
        else:
            # 子アイテムとして追加したラベルを削除
            if self._label_item is not None:
                self._label_item.setParentItem(None)
                if self._label_item.scene():
                    self._label_item.scene().removeItem(self._label_item)
                self._label_item = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent_dialog.on_point_clicked(self)
        super().mousePressEvent(event)


class FixedLabelItem(QGraphicsSimpleTextItem):
    """ItemIgnoresTransformations で常にスクリーン固定サイズの地番ラベル"""

    def __init__(self, text, scene_x, scene_y, color, bold=False):
        super().__init__(text)
        f = QFont("Meiryo UI")
        f.setPointSize(_LABEL_FONT_SIZE)
        f.setBold(bold)
        self.setFont(f)
        self.setBrush(QBrush(QColor(color)))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        # setPos はシーン座標。ItemIgnoresTransformations では
        # boudingRect() がスクリーンピクセル単位になるため
        # "scene_x - br.width()/2" はズーム時に座標系が混在してズレる。
        # 正しくはシーン座標のみで指定し、テキスト左端をセントロイドに合わせる。
        self.setPos(scene_x, scene_y)
        self.setZValue(8)


# ============================================================
# プレビューキャンバス
# ============================================================

class PreviewCanvas(QGraphicsView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(C_CANVAS)))
        self._zoom = 0

    def clear(self):
        self._scene.clear()
        self._zoom = 0
        self.resetTransform()

    def fit(self):
        r = self._scene.itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        f = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._zoom += 1 if event.angleDelta().y() > 0 else -1
        if -25 <= self._zoom <= 40:
            self.scale(f, f)
        else:
            self._zoom = max(-25, min(40, self._zoom))


# ============================================================
# GCPテーブル
# ============================================================

class GCPTableWidget(QTableWidget):
    # 任意X/Y列は削除 — 内部座標は ZukakuState.selected_gcps で保持
    HEADERS = ['No', '点番', '平面直角 X (北方向) [m]', '平面直角 Y (東方向) [m]']

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(110)

    def add_row(self, pid):
        """行を追加する。任意座標は表示しない（ZukakuState側で保持）"""
        row = self.rowCount()
        self.insertRow(row)
        for col, val in enumerate([str(row + 1), str(pid)]):
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setBackground(QBrush(QColor('#edf2f9')))
            item.setForeground(QBrush(QColor(C_TEXT)))
            self.setItem(row, col, item)
        self.setItem(row, 2, QTableWidgetItem(''))
        self.setItem(row, 3, QTableWidgetItem(''))
        self.scrollToBottom()
        self.setCurrentCell(row, 2)

    def get_data(self, selected_gcps):
        """
        (src_pts, dst_pts, error_rows) を返す。
        selected_gcps: [(pid, disp_x, disp_y), ...] — ZukakuState.selected_gcps
        テーブルの各行と selected_gcps のインデックスが対応。
        """
        src, dst, errs = [], [], []
        for r in range(self.rowCount()):
            try:
                if r >= len(selected_gcps):
                    break
                _, disp_x, disp_y = selected_gcps[r]
                xt = (self.item(r, 2).text() or '').strip()
                yt = (self.item(r, 3).text() or '').strip()
                if not xt or not yt:
                    continue
                src.append((disp_x, disp_y))
                dst.append((float(xt), float(yt)))
            except (ValueError, AttributeError):
                errs.append(r + 1)
        return src, dst, errs


# ============================================================
# メインダイアログ
# ============================================================

class MOJXMLDialog(QDialog):

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.parser = MOJXMLParser()
        self._has_koaza = False
        self.zg_states = []          # List[ZukakuState]
        self.current_zg_idx = 0      # 現在選択中の図郭インデックス
        self._draw_oaza   = ''
        self._draw_koaza  = ''
        self._draw_chiban = []

        self.setWindowTitle("MOJ 任意座標変換ローダー")
        self.setMinimumSize(1400, 900)
        self.resize(1500, 960)
        self.setStyleSheet(_STYLE)
        self._build_ui()

    # ─────────────────────────────────────────
    # UI 構築
    # ─────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)

        title = QLabel("  📐  MOJ 任意座標変換ローダー  —  法務局備付地図（任意座標系）図郭別変換対応版")
        title.setObjectName("lbl_title")
        root.addWidget(title)

        main_h = QSplitter(Qt.Horizontal)
        main_h.setChildrenCollapsible(False)
        root.addWidget(main_h, stretch=1)

        main_h.addWidget(self._build_left())

        right_v = QSplitter(Qt.Vertical)
        right_v.setChildrenCollapsible(False)
        right_v.addWidget(self._build_canvas_panel())
        right_v.addWidget(self._build_gcp_area())
        right_v.setSizes([480, 440])
        main_h.addWidget(right_v)
        main_h.setSizes([320, 1080])

        row = QHBoxLayout()
        row.addStretch()
        cb = QPushButton("  ✕  閉じる")
        cb.setFixedWidth(110)
        cb.clicked.connect(self.reject)
        row.addWidget(cb)
        root.addLayout(row)

    # ── 左パネル ──
    def _build_left(self):
        w = QWidget()
        w.setFixedWidth(320)
        lv = QVBoxLayout(w)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.setSpacing(8)

        # ファイル選択
        fg = QGroupBox("📁  ファイル選択（ZIP / XML）")
        fh = QHBoxLayout(fg)
        fh.setContentsMargins(8, 16, 8, 8)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("ZIPまたはXMLファイル...")
        self.file_edit.setReadOnly(True)
        btn_f = QPushButton("参照...")
        btn_f.setFixedWidth(60)
        btn_f.clicked.connect(self._on_file_select)
        fh.addWidget(self.file_edit)
        fh.addWidget(btn_f)
        lv.addWidget(fg)

        # ファイル情報
        mg = QGroupBox("📋  ファイル情報")
        gg = QGridLayout(mg)
        gg.setContentsMargins(10, 18, 10, 10)
        gg.setHorizontalSpacing(8)
        gg.setVerticalSpacing(5)
        self.lbl_code  = QLabel("―")
        self.lbl_muni  = QLabel("―")
        self.lbl_coord = QLabel("―")
        self.lbl_map   = QLabel("―")
        for i, (cap, w2) in enumerate([
            ("コード :",   self.lbl_code),
            ("市区町村 :", self.lbl_muni),
            ("座標系 :",   self.lbl_coord),
            ("地図名 :",   self.lbl_map),
        ]):
            lb = QLabel(cap)
            lb.setObjectName("lbl_sub")
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            w2.setStyleSheet("font-weight: bold;")
            gg.addWidget(lb, i, 0)
            gg.addWidget(w2, i, 1)
        gg.setColumnStretch(1, 1)
        lv.addWidget(mg)

        # 住所選択
        ag = QGroupBox("🗾  住所・地番選択")
        av = QVBoxLayout(ag)
        av.setContentsMargins(10, 20, 10, 10)
        av.setSpacing(5)

        row_oaza = QHBoxLayout()
        lb_o = QLabel("大字 :")
        lb_o.setObjectName("lbl_sub")
        lb_o.setFixedWidth(44)
        lb_o.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.combo_oaza = QComboBox()
        self.combo_oaza.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_oaza.currentTextChanged.connect(self._on_oaza_changed)
        row_oaza.addWidget(lb_o)
        row_oaza.addWidget(self.combo_oaza)
        av.addLayout(row_oaza)

        self.koaza_row = QWidget()
        row_k = QHBoxLayout(self.koaza_row)
        row_k.setContentsMargins(0, 0, 0, 0)
        lb_k = QLabel("小字 :")
        lb_k.setObjectName("lbl_sub")
        lb_k.setFixedWidth(44)
        lb_k.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.combo_koaza = QComboBox()
        self.combo_koaza.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_koaza.currentTextChanged.connect(self._on_koaza_changed)
        row_k.addWidget(lb_k)
        row_k.addWidget(self.combo_koaza)
        av.addWidget(self.koaza_row)

        self.lbl_no_koaza = QLabel("（この大字に小字データはありません）")
        self.lbl_no_koaza.setObjectName("lbl_no_koaza")
        self.lbl_no_koaza.hide()
        av.addWidget(self.lbl_no_koaza)

        lb_ch = QLabel("地番（複数選択可）:")
        lb_ch.setObjectName("lbl_sub")
        av.addWidget(lb_ch)

        self.list_chiban = QListWidget()
        self.list_chiban.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_chiban.setAlternatingRowColors(True)
        self.list_chiban.setMinimumHeight(120)
        av.addWidget(self.list_chiban)

        sel_row = QHBoxLayout()
        btn_all = QPushButton("全選択")
        btn_all.setFixedWidth(64)
        btn_all.clicked.connect(self.list_chiban.selectAll)
        btn_clr = QPushButton("解除")
        btn_clr.setFixedWidth(50)
        btn_clr.clicked.connect(self.list_chiban.clearSelection)
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_clr)
        sel_row.addStretch()
        av.addLayout(sel_row)
        lv.addWidget(ag)

        self.btn_draw = QPushButton("  🗺   図郭確定・ポリゴン表示")
        self.btn_draw.setEnabled(False)
        self.btn_draw.setMinimumHeight(30)
        self.btn_draw.clicked.connect(self._on_draw)
        lv.addWidget(self.btn_draw)

        self.lbl_stat = QLabel("ファイルを読み込んでください")
        self.lbl_stat.setObjectName("lbl_stat")
        self.lbl_stat.setWordWrap(True)
        self.lbl_stat.setMinimumHeight(52)
        lv.addWidget(self.lbl_stat)
        lv.addStretch()
        return w

    # ── キャンバスパネル ──
    def _build_canvas_panel(self):
        w = QWidget()
        cv = QVBoxLayout(w)
        cv.setContentsMargins(4, 4, 4, 0)
        cv.setSpacing(3)

        hint = QLabel(
            "  【プレビューキャンバス】  "
            "ホイール: ズーム　ドラッグ: パン　"
            "青丸クリック → 現在の図郭タブにGCP登録"
        )
        hint.setObjectName("lbl_canvas_hint")
        cv.addWidget(hint)

        self.canvas = PreviewCanvas()
        cv.addWidget(self.canvas, stretch=1)

        row = QHBoxLayout()
        fit_btn = QPushButton("⤢ 全体表示")
        fit_btn.setFixedWidth(100)
        fit_btn.clicked.connect(self.canvas.fit)
        row.addStretch()
        row.addWidget(fit_btn)
        cv.addLayout(row)
        return w

    # ── GCP・変換エリア（図郭タブ + 共通CRS + 追加ボタン）──
    def _build_gcp_area(self):
        w = QWidget()
        gv = QVBoxLayout(w)
        gv.setContentsMargins(4, 4, 4, 4)
        gv.setSpacing(6)

        # 図郭タブ説明ラベル
        info = QLabel(
            "  📍  図郭タブを切り替えてGCPを登録・変換実行してください  "
            "（各図郭が独立した変換パラメータを持ちます）"
        )
        info.setObjectName("lbl_canvas_hint")
        gv.addWidget(info)

        # 図郭タブウィジェット（_draw_polygons()で動的に構築）
        self.zg_tab_widget = QTabWidget()
        self.zg_tab_widget.currentChanged.connect(self._on_zg_tab_changed)
        placeholder = QLabel("  ポリゴン表示後に各図郭のタブが表示されます")
        placeholder.setObjectName("lbl_sub")
        placeholder.setAlignment(Qt.AlignCenter)
        self.zg_tab_widget.addTab(placeholder, "（図郭なし）")
        gv.addWidget(self.zg_tab_widget, stretch=1)

        # 共通CRS + 最終出力ボタン
        bottom_grp = QGroupBox("🌐  共通出力設定  &  レイヤ追加 / エクスポート")
        bg = QVBoxLayout(bottom_grp)
        bg.setContentsMargins(10, 18, 10, 10)
        bg.setSpacing(8)

        # CRS選択
        crs_row = QHBoxLayout()
        lb_crs = QLabel("出力 CRS :")
        lb_crs.setObjectName("lbl_sub")
        lb_crs.setFixedWidth(70)
        lb_crs.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        crs_row.addWidget(lb_crs)

        if QGIS_CRS_WIDGET:
            self.crs_widget = QgsProjectionSelectionWidget()
            self.crs_widget.setCrs(QgsCoordinateReferenceSystem('EPSG:6677'))
            self.crs_widget.setToolTip("全図郭共通の出力CRS\nJGD2011 平面直角: I=6669 … XIX=6687")
            crs_row.addWidget(self.crs_widget)
            self.epsg_edit = None
        else:
            self.crs_widget = None
            self.epsg_edit = QLineEdit("6677")
            self.epsg_edit.setFixedWidth(72)
            lb_e = QLabel("EPSGコード（JGD2011: 6669〜6687）")
            lb_e.setObjectName("lbl_sub")
            crs_row.addWidget(self.epsg_edit)
            crs_row.addWidget(lb_e)
            crs_row.addStretch()

        bg.addLayout(crs_row)

        # 出力ボタン行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_add_layer = QPushButton("  ✅  全図郭をQGISレイヤに追加")
        self.btn_add_layer.setObjectName("btn_add_layer")
        self.btn_add_layer.setMinimumWidth(220)
        self.btn_add_layer.setEnabled(False)
        self.btn_add_layer.clicked.connect(self._on_add_layer)

        self.lbl_zg_status = QLabel("")
        self.lbl_zg_status.setObjectName("lbl_sub")
        self.lbl_zg_status.setWordWrap(True)

        btn_row.addWidget(self.btn_add_layer)
        btn_row.addWidget(self.lbl_zg_status, stretch=1)
        bg.addLayout(btn_row)

        gv.addWidget(bottom_grp)
        return w

    # ─────────────────────────────────────────
    # 図郭タブ動的構築
    # ─────────────────────────────────────────

    def _build_all_zg_tabs(self):
        """zg_states に基づいて図郭タブを構築する"""
        # シグナルを一時切断して再構築中の誤発火を防ぐ
        self.zg_tab_widget.currentChanged.disconnect(self._on_zg_tab_changed)
        while self.zg_tab_widget.count():
            self.zg_tab_widget.removeTab(0)

        for idx, state in enumerate(self.zg_states):
            tab_w = self._build_zg_tab(state, idx)
            label = f"図郭 {idx + 1}  [{state.map_no}]"
            self.zg_tab_widget.addTab(tab_w, label)

        self.zg_tab_widget.currentChanged.connect(self._on_zg_tab_changed)
        self.zg_tab_widget.setCurrentIndex(0)
        # setCurrentIndex が connect 前なので手動発火
        self._on_zg_tab_changed(0)

    def _build_zg_tab(self, state, idx):
        """1図郭分のタブコンテンツを構築し、state にUIへの参照を格納する"""
        tab = QWidget()
        tv = QVBoxLayout(tab)
        tv.setContentsMargins(8, 8, 8, 8)
        tv.setSpacing(5)

        # GCPテーブル
        state.gcp_table = GCPTableWidget()
        tv.addWidget(state.gcp_table, stretch=1)

        # GCP操作ボタン
        gcp_btn = QHBoxLayout()
        btn_del = QPushButton("選択行削除")
        btn_del.setFixedWidth(88)
        btn_del.clicked.connect(lambda _, i=idx: self._on_del_gcp(i))
        btn_clr = QPushButton("全クリア")
        btn_clr.setFixedWidth(70)
        btn_clr.clicked.connect(lambda _, i=idx: self._on_clear_gcp(i))
        gcp_btn.addWidget(btn_del)
        gcp_btn.addWidget(btn_clr)
        gcp_btn.addStretch()
        tv.addLayout(gcp_btn)

        # 区切り線
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {C_INFO_BD};")
        tv.addWidget(sep)

        # 変換方式（各図郭独立）
        method_row = QHBoxLayout()
        lb_m = QLabel("変換方式 :")
        lb_m.setObjectName("lbl_sub")
        lb_m.setFixedWidth(70)
        state.radio_auto    = QRadioButton("自動（推奨）")
        state.radio_helmert = QRadioButton("ヘルマート（2点以上）")
        state.radio_affine  = QRadioButton("アフィン（3点以上）")
        state.radio_auto.setChecked(True)
        rg = QButtonGroup(tab)   # parent=tab でタブごとに独立
        rg.addButton(state.radio_auto)
        rg.addButton(state.radio_helmert)
        rg.addButton(state.radio_affine)
        method_row.addWidget(lb_m)
        method_row.addWidget(state.radio_auto)
        method_row.addWidget(state.radio_helmert)
        method_row.addWidget(state.radio_affine)
        method_row.addStretch()
        tv.addLayout(method_row)

        # 変換実行ボタン
        exec_row = QHBoxLayout()
        state.btn_exec_zg = QPushButton(
            f"  🔄  図郭 {idx + 1} の変換パラメータを算出"
        )
        state.btn_exec_zg.setObjectName("btn_exec_zg")
        state.btn_exec_zg.setMinimumWidth(220)
        state.btn_exec_zg.clicked.connect(lambda _, i=idx: self._on_exec_zg(i))
        exec_row.addWidget(state.btn_exec_zg)
        exec_row.addStretch()
        tv.addLayout(exec_row)

        # 変換結果ラベル
        state.lbl_result = QLabel("（GCPを2点以上登録して変換を実行してください）")
        state.lbl_result.setObjectName("lbl_result")
        state.lbl_result.setWordWrap(True)
        state.lbl_result.setMinimumHeight(44)
        tv.addWidget(state.lbl_result)

        return tab

    # ─────────────────────────────────────────
    # ファイル読み込み・住所選択
    # ─────────────────────────────────────────

    def _on_file_select(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "法務局地図データを選択", "",
            "法務局地図データ (*.zip *.xml);;ZIP (*.zip);;XML (*.xml)"
        )
        if not path:
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.parser.load_file(path)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "読み込みエラー", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.file_edit.setText(path)
        m = self.parser.meta
        self.lbl_code.setText(m.get('市区町村コード', '―'))
        self.lbl_muni.setText(m.get('市区町村名',     '―'))
        self.lbl_coord.setText(m.get('座標系',         '―'))
        self.lbl_map.setText(m.get('地図名',           '―'))

        self.combo_oaza.blockSignals(True)
        self.combo_oaza.clear()
        oaza_list = self.parser.get_oaza_list()
        self.combo_oaza.addItems(oaza_list)
        self.combo_oaza.blockSignals(False)
        if oaza_list:
            self._on_oaza_changed(oaza_list[0])

        self.btn_draw.setEnabled(True)
        self.canvas.clear()
        self.lbl_stat.setText(
            f"✓ 読み込み完了  筆数: {len(self.parser.fude_list)}"
            f"  図郭数: {len(self.parser.zukaku_list)}"
        )

    def _on_oaza_changed(self, oaza_name):
        self.combo_koaza.blockSignals(True)
        self.combo_koaza.clear()
        koaza_list = self.parser.get_koaza_list(oaza_name)
        self._has_koaza = bool(koaza_list)
        if self._has_koaza:
            self.combo_koaza.addItems(koaza_list)
            self.koaza_row.show()
            self.lbl_no_koaza.hide()
            self.combo_koaza.blockSignals(False)
            self._reload_chiban(oaza_name, koaza_list[0])
        else:
            self.koaza_row.hide()
            self.lbl_no_koaza.show()
            self.combo_koaza.blockSignals(False)
            self._reload_chiban(oaza_name, None)

    def _on_koaza_changed(self, koaza_name):
        self._reload_chiban(self.combo_oaza.currentText(), koaza_name or None)

    def _reload_chiban(self, oaza_name, koaza_name):
        self.list_chiban.clear()
        for ch in self.parser.get_chiban_list(oaza_name, koaza_name):
            self.list_chiban.addItem(QListWidgetItem(ch))

    # ─────────────────────────────────────────
    # ポリゴン描画
    # ─────────────────────────────────────────

    def _on_draw(self):
        oaza  = self.combo_oaza.currentText()
        koaza = self.combo_koaza.currentText() if self._has_koaza else None
        sel   = self.list_chiban.selectedItems()
        if not sel:
            QMessageBox.warning(self, "選択エラー", "地番を1件以上選択してください")
            return
        chiban_list = [it.text() for it in sel]
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._draw_polygons(oaza, koaza, chiban_list)
        except Exception as e:
            QMessageBox.critical(self, "表示エラー", str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def _draw_polygons(self, oaza_name, koaza_name, chiban_list):
        """
        指定地番が属する図郭を特定し、図郭ごとにZukakuStateを作成。
        キャンバスに描画し、図郭タブを構築する。
        """
        self.canvas.clear()
        self.zg_states.clear()
        self.current_zg_idx = 0
        self.btn_add_layer.setEnabled(False)
        self.lbl_zg_status.setText("")
        # レイヤ名生成用に選択情報を保存
        self._draw_oaza   = oaza_name
        self._draw_koaza  = koaza_name
        self._draw_chiban = chiban_list[:]

        # ① 対象筆
        target_fude = self.parser.get_fude_by_oaza_koaza_chiban(
            oaza_name, koaza_name, chiban_list
        )
        if not target_fude:
            QMessageBox.warning(self, "データなし", "指定条件に合致する筆が見つかりません")
            return

        target_fude_ids = {f['id'] for f in target_fude}

        # ② 対象筆が属する図郭を取得
        target_zukaku = self.parser.get_zukaku_for_fude_ids(target_fude_ids)
        if not target_zukaku:
            QMessageBox.warning(self, "図郭なし", "対象筆が含まれる図郭が見つかりません")
            return

        # ③ 図郭ごとにZukakuStateを作成
        for zg_idx, zg in enumerate(target_zukaku):
            fude_in_zg = [
                self.parser.fude_by_id[fid]
                for fid in zg['筆参照_ids']
                if fid in self.parser.fude_by_id
            ]
            state = ZukakuState(zg, fude_in_zg, zg_idx)
            self.zg_states.append(state)

        # ④ 全図郭のポリゴン座標を収集してキャンバスに描画
        scene = self.canvas._scene

        def to_sc(x, y):
            return (x, -y)  # Y軸反転

        all_scene_coords = []

        for zg_idx, state in enumerate(self.zg_states):
            is_current = (zg_idx == 0)
            fill_rgba  = state.fill_active if is_current else state.fill_inactive
            stroke_col = state.stroke_active

            # 図郭内の全ポリゴンを収集して境界ボックスを計算
            zg_real_coords = []

            for fude in state.fude_list:
                fid = fude['id']
                sid = fude.get('surface_id')
                if not sid:
                    continue
                coords = self.parser.build_polygon_coords(sid)
                if not coords:
                    continue

                zg_real_coords.extend(coords)
                all_scene_coords.extend([to_sc(p[0], p[1]) for p in coords])

                is_target = fid in target_fude_ids
                poly = QPolygonF([QPointF(*to_sc(p[0], p[1])) for p in coords])
                item = QGraphicsPolygonItem(poly)
                item.setBrush(QBrush(QColor(*fill_rgba)))
                item.setPen(QPen(QColor(stroke_col if is_target else '#607080'), 
                                 1.0 if is_target else 0.5))
                item.setZValue(5 if is_target else 2)
                scene.addItem(item)
                state.poly_items[fid] = item

                # 地番ラベル
                scx, scy = to_sc(*self.parser.get_centroid(coords))
                lbl = FixedLabelItem(
                    fude.get('地番', ''), scx, scy,
                    '#fff8e0' if is_target else '#88b8cc',
                    bold=is_target
                )
                scene.addItem(lbl)

            # 図郭の実座標バウンディングボックスを計算
            if zg_real_coords:
                xs = [p[0] for p in zg_real_coords]
                ys = [p[1] for p in zg_real_coords]
                state.bbox = (min(xs), max(xs), min(ys), max(ys))

            # ⑤ 図郭バウンディングボックス内の筆界点を描画（固定サイズ）
            if zg_real_coords:
                span = ((max(xs) - min(xs)) + (max(ys) - min(ys))) or 1.0
                margin = span * 0.04
                x_lo, x_hi = min(xs) - margin, max(xs) + margin
                y_lo, y_hi = min(ys) - margin, max(ys) + margin

                for pid, (px, py) in self.parser.points.items():
                    if not (x_lo <= px <= x_hi and y_lo <= py <= y_hi):
                        continue
                    if pid in state.point_items:
                        continue  # 既登録（隣接図郭との共有点はスキップ）
                    sx, sy = to_sc(px, py)
                    pt = FixedPointItem(sx, sy, pid, self,
                                        radius=_PT_RADIUS,
                                        color=state.point_color)
                    pt.setVisible(is_current)
                    scene.addItem(pt)
                    state.point_items[pid] = pt

        self.canvas.fit()

        # ⑥ 図郭タブを構築
        self._build_all_zg_tabs()

        n_zg  = len(self.zg_states)
        n_tgt = len(target_fude)
        self.lbl_stat.setText(
            f"✓ 描画完了  対象筆: {n_tgt}  対象図郭: {n_zg}\n"
            f"図郭タブを切り替えてGCPを登録し、各図郭の変換を実行してください"
        )
        self._update_zg_status()

    # ─────────────────────────────────────────
    # 図郭タブ切り替え
    # ─────────────────────────────────────────

    def _on_zg_tab_changed(self, idx):
        if not self.zg_states or idx < 0 or idx >= len(self.zg_states):
            return
        self.current_zg_idx = idx

        for zg_i, state in enumerate(self.zg_states):
            is_cur = (zg_i == idx)
            fill_rgba  = state.fill_active   if is_cur else state.fill_inactive
            stroke_col = state.stroke_active  if is_cur else '#607080'

            for fid, item in state.poly_items.items():
                is_target = fid in state.fude_ids
                item.setBrush(QBrush(QColor(*fill_rgba)))
                item.setPen(QPen(QColor(stroke_col),
                                 1.0 if (is_cur and is_target) else 0.5))

            for pt in state.point_items.values():
                pt.setVisible(is_cur)

        # 現在図郭のGCP登録済み点を赤にリストア
        cur = self.zg_states[idx]
        for pid, _, _ in cur.selected_gcps:
            if pid in cur.point_items:
                cur.point_items[pid].mark_as_gcp(True)

    # ─────────────────────────────────────────
    # GCP 操作
    # ─────────────────────────────────────────

    def on_point_clicked(self, pt_item):
        """筆界点クリック → 現在の図郭タブにGCP登録"""
        if not self.zg_states:
            return
        state = self.zg_states[self.current_zg_idx]

        pid = pt_item.point_id
        if any(p == pid for p, _, _ in state.selected_gcps):
            QMessageBox.information(
                self, "重複", f"点番 {pid} は既にこの図郭のGCPとして登録されています"
            )
            return

        disp_x = pt_item._scene_x
        disp_y = -pt_item._scene_y   # Y逆転を戻す

        state.gcp_table.add_row(pid)
        pt_item.mark_as_gcp(True)
        state.selected_gcps.append((pid, disp_x, disp_y))

        map_no = state.map_no
        QToolTip.showText(
            QCursor.pos(),
            f"図郭[{map_no}] に GCP登録: 点番 {pid}\n"
            f"任意座標 ({disp_x:.3f}, {disp_y:.3f})\n"
            "「平面直角X(北)」「Y(東)」列に座標値を入力してください"
        )

    def _on_del_gcp(self, zg_idx):
        if zg_idx >= len(self.zg_states):
            return
        state = self.zg_states[zg_idx]
        rows = sorted(
            {i.row() for i in state.gcp_table.selectedItems()},
            reverse=True
        )
        for row in rows:
            if row < len(state.selected_gcps):
                pid = state.selected_gcps[row][0]
                if pid in state.point_items:
                    state.point_items[pid].mark_as_gcp(False)
                state.selected_gcps.pop(row)
            state.gcp_table.removeRow(row)

    def _on_clear_gcp(self, zg_idx):
        if zg_idx >= len(self.zg_states):
            return
        state = self.zg_states[zg_idx]
        for pid, _, _ in state.selected_gcps:
            if pid in state.point_items:
                state.point_items[pid].mark_as_gcp(False)
        state.selected_gcps.clear()
        state.gcp_table.setRowCount(0)
        state.transform_func = None
        state.params_text = ''
        if state.lbl_result:
            state.lbl_result.setText("（GCPを2点以上登録して変換を実行してください）")
        self._update_zg_status()

    # ─────────────────────────────────────────
    # 図郭別 変換実行
    # ─────────────────────────────────────────

    def _on_exec_zg(self, zg_idx):
        if zg_idx >= len(self.zg_states):
            return
        state = self.zg_states[zg_idx]

        src, dst, errs = state.gcp_table.get_data(state.selected_gcps)
        if errs:
            QMessageBox.warning(
                self, "入力エラー",
                f"行 {errs} に無効な値があります\n"
                "「平面直角X(北)」「平面直角Y(東)」に数値を入力してください"
            )
            return
        if len(src) < 2:
            QMessageBox.warning(
                self, "GCP不足",
                f"図郭 {zg_idx + 1} のGCPが2点未満です\n"
                "筆界点をクリックしてGCPを登録し、平面直角座標を入力してください"
            )
            return

        method = None
        if state.radio_helmert.isChecked():
            method = 'helmert'
        elif state.radio_affine.isChecked():
            method = 'affine'

        try:
            params, func, rmse = auto_transform(src, dst, force_method=method)
            state.transform_func = func
            state.params_text = format_params(params)
            state.lbl_result.setText(
                f"✓ 変換完了  " + state.params_text
            )
            # タブのテキストに ✓ マークを追加
            label = f"✓ 図郭 {zg_idx + 1}  [{state.map_no}]"
            self.zg_tab_widget.setTabText(zg_idx, label)

        except Exception as e:
            QMessageBox.critical(self, f"図郭 {zg_idx + 1} 変換エラー", str(e))
            return

        self._update_zg_status()

    def _update_zg_status(self):
        """全図郭の変換状態を確認し、出力ボタンの有効/無効を更新"""
        if not self.zg_states:
            self.lbl_zg_status.setText("")
            self.btn_add_layer.setEnabled(False)
            self.btn_export.setEnabled(False)
            return

        done = [s for s in self.zg_states if s.transform_func is not None]
        total = len(self.zg_states)
        self.lbl_zg_status.setText(
            f"変換完了: {len(done)} / {total} 図郭"
        )
        has_any = len(done) > 0
        self.btn_add_layer.setEnabled(has_any and QGIS_AVAILABLE)

    # ─────────────────────────────────────────
    # レイヤ追加 / エクスポート
    # ─────────────────────────────────────────

    def _get_crs(self):
        if self.crs_widget is not None:
            crs = self.crs_widget.crs()
            return crs if crs.isValid() else None
        try:
            crs = QgsCoordinateReferenceSystem(
                f'EPSG:{self.epsg_edit.text().strip()}'
            )
            return crs if crs.isValid() else None
        except Exception:
            return None

    def _on_add_layer(self):
        if not QGIS_AVAILABLE:
            QMessageBox.critical(self, "エラー", "QGISが利用できません")
            return
        crs = self._get_crs()
        if crs is None:
            QMessageBox.warning(self, "CRS未設定", "有効な出力CRSを選択してください")
            return

        done = [s for s in self.zg_states if s.transform_func is not None]
        if not done:
            QMessageBox.warning(self, "未変換", "少なくとも1つの図郭で変換を実行してください")
            return

        undone = [i + 1 for i, s in enumerate(self.zg_states)
                  if s.transform_func is None]
        if undone:
            ans = QMessageBox.question(
                self, "未変換の図郭あり",
                f"図郭 {undone} は変換未実行です。\n変換済みの図郭のみ追加しますか？",
                QMessageBox.Yes | QMessageBox.Cancel
            )
            if ans != QMessageBox.Yes:
                return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            # 市町村名 + 大字名 [+ 小字名] + 地番リスト
            muni  = self.parser.meta.get('市区町村名', '地図')
            oaza  = getattr(self, '_draw_oaza',  '')
            koaza = getattr(self, '_draw_koaza', '') or ''
            chibs = getattr(self, '_draw_chiban', [])
            # 地番は最大4件表示、それ以上は省略
            if len(chibs) <= 4:
                chiban_str = '_'.join(chibs)
            else:
                chiban_str = '_'.join(chibs[:4]) + f'ほか{len(chibs)-4}件'
            if koaza:
                base = f"{muni}_{oaza}_{koaza}_{chiban_str}周辺"
            else:
                base = f"{muni}_{oaza}_{chiban_str}周辺"
            added = 0
            for zg_idx, state in enumerate(self.zg_states):
                if state.transform_func is None:
                    continue
                self._create_layer_for_state(state, base, crs)
                added += 1
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "レイヤ追加エラー", str(e))
            return

        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "完了",
            f"{added} 件の図郭レイヤをQGISプロジェクトに追加しました"
        )

    def _create_layer_for_state(self, state, base_name, crs):
        """
        1図郭分のメモリレイヤを作成してQGISに追加。
        transform_func(disp_x, disp_y) → (plane_X=北, plane_Y=東)
        QgsPointXY(east=plane_Y, north=plane_X)
        """
        layer_name = f"{base_name}_{state.map_no}"
        layer = QgsVectorLayer('Polygon', layer_name, 'memory')
        layer.setCrs(crs)
        pr = layer.dataProvider()
        pr.addAttributes([
            QgsField('地番',       _STR_TYPE),
            QgsField('大字名',     _STR_TYPE),
            QgsField('小字名',     _STR_TYPE),
            QgsField('座標値種別', _STR_TYPE),
            QgsField('地図番号',   _STR_TYPE),
        ])
        layer.updateFields()

        features = []
        for fude in state.fude_list:
            sid = fude.get('surface_id')
            if not sid:
                continue
            coords = self.parser.build_polygon_coords(sid)
            if len(coords) < 4:
                continue

            qgs_pts = []
            for disp_x, disp_y in coords:
                try:
                    # plane_X = 北方向(ユーザーがXとして入力)
                    # plane_Y = 東方向(ユーザーがYとして入力)
                    plane_X, plane_Y = state.transform_func(disp_x, disp_y)
                    # QgsPointXY(x=東, y=北)
                    qgs_pts.append(QgsPointXY(plane_Y, plane_X))
                except Exception:
                    continue

            if len(qgs_pts) < 4:
                continue

            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolygonXY([qgs_pts]))
            feat.setAttributes([
                fude.get('地番', ''),
                fude.get('大字名', ''),
                fude.get('小字名', ''),
                fude.get('座標値種別', ''),
                state.map_no,
            ])
            features.append(feat)

        pr.addFeatures(features)
        layer.updateExtents()

        # スタイル
        sym = layer.renderer().symbol()
        sym.setColor(QColor(*state.fill_active))
        sym.symbolLayer(0).setStrokeColor(QColor(state.stroke_active))
        sym.symbolLayer(0).setStrokeWidth(0.3)

        # ラベル
        ls = QgsPalLayerSettings()
        ls.fieldName = '地番'
        ls.enabled = True
        tf = QgsTextFormat()
        tf.setColor(QColor(C_TEXT))
        tf.setSize(7)
        ls.setFormat(tf)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(ls))
        layer.setLabelsEnabled(True)

        QgsProject.instance().addMapLayer(layer)

