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
mojxml_arbitrary_loader.py
MOJ任意座標変換ローダー QGISプラグインメインクラス
"""

import os

from PyQt5.QtWidgets import QAction
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QCoreApplication, Qt


class MOJXMLArbitraryLoader:
    """QGISプラグインクラス（法務局備付地図・任意座標系変換ローダー）"""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None

    def initGui(self):
        """プラグインGUIの初期化（QGISがプラグインをロードした時に呼ばれる）"""
        icon_path = os.path.join(self.plugin_dir, 'icon.svg')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action = QAction(
            icon,
            "MOJ 任意座標変換ローダー",
            self.iface.mainWindow()
        )
        self.action.setObjectName("mojXMLArbLoader")
        self.action.setStatusTip("法務局備付地図データ（任意座標系）を読み込み・変換します")
        self.action.setWhatsThis(
            "法務局備付地図データ（ZIP/XML・任意座標系）を読み込み、"
            "GCPを用いてヘルマート/アフィン変換で平面直角座標系へ変換します"
        )
        self.action.triggered.connect(self.run)

        # メニューとツールバーへの登録
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("&MOJ 任意座標変換ローダー", self.action)

    def unload(self):
        """プラグインのアンロード時にGUI要素を削除する"""
        self.iface.removePluginVectorMenu("&MOJ 任意座標変換ローダー", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.action:
            del self.action
        if self.dialog:
            self.dialog.close()
            del self.dialog

    def run(self):
        """プラグインを実行する（ダイアログを表示）"""
        from .dialog import MOJXMLDialog

        # ダイアログは毎回新規作成（状態をリセット）
        self.dialog = MOJXMLDialog(
            iface=self.iface,
            parent=self.iface.mainWindow()
        )
        self.dialog.setWindowModality(Qt.NonModal)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
