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
xml_parser.py
法務局備付地図データ XML解析モジュール（任意座標系専用）

座標値はXMLの X,Y を日本測量座標に合わせて (Y, X) → (lon_like, lat_like) の順に格納します。
（XMLのX = 縦方向、XMLのY = 横方向 → QGISではX=水平,Y=垂直なのでswap必要）
"""

import zipfile
import io
import os
import sys
import importlib.util
from xml.etree import ElementTree as ET

# 同梱の defusedxml (vendor/) を importlib で直接読み込む
# sys.path を操作せず、ファイルパスを直接指定することで
# QGISのインポート機構との干渉を避ける
def _load_vendored_defusedxml():
    _base = os.path.dirname(os.path.abspath(__file__))
    _init  = os.path.join(_base, 'vendor', 'defusedxml', '__init__.py')
    _etree = os.path.join(_base, 'vendor', 'defusedxml', 'ElementTree.py')

    # defusedxml パッケージ本体を登録
    spec_pkg = importlib.util.spec_from_file_location(
        'defusedxml', _init,
        submodule_search_locations=[os.path.dirname(_init)]
    )
    pkg = importlib.util.module_from_spec(spec_pkg)
    sys.modules['defusedxml'] = pkg
    spec_pkg.loader.exec_module(pkg)

    # defusedxml.ElementTree サブモジュールを登録
    spec_et = importlib.util.spec_from_file_location('defusedxml.ElementTree', _etree)
    mod_et = importlib.util.module_from_spec(spec_et)
    sys.modules['defusedxml.ElementTree'] = mod_et
    spec_et.loader.exec_module(mod_et)

    return mod_et.fromstring

_safe_fromstring = _load_vendored_defusedxml()


NS_MOJ = 'http://www.moj.go.jp/MINJI/tizuxml'
NS_ZMN = 'http://www.moj.go.jp/MINJI/tizuzumen'


def _t(ns, local):
    return f'{{{ns}}}{local}'


def _txt(elem, tag, default=''):
    child = elem.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return default


class MOJXMLParser:
    """法務局備付地図データXMLパーサ（任意座標系専用）"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.meta = {}
        self.points = {}    # pid -> (x_disp, y_disp) ※座標変換後の表示用
        self.curves = {}    # cid -> [(x, y), ...]
        self.surfaces = {}  # fid -> [cid, ...]
        self.fude_list = [] # 筆リスト
        self.zukaku_list = []  # 図郭リスト
        self.fude_by_id = {}  # 筆id -> 筆dict
        self.xml_bytes = None  # 元のXMLバイト列（エクスポート用）

    def load_file(self, file_path):
        """
        ZIPまたはXMLファイルを読み込む。
        任意座標系でない場合は ValueError を送出。
        """
        self.reset()

        if file_path.lower().endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zf:
                xml_names = [n for n in zf.namelist()
                             if n.lower().endswith('.xml')]
                if not xml_names:
                    raise ValueError("ZIP内にXMLファイルが見つかりません")

                found = False
                for xml_name in xml_names:
                    raw = zf.read(xml_name)
                    try:
                        root = _safe_fromstring(raw)
                    except ET.ParseError as e:
                        raise ValueError(f"XML解析エラー: {e}")

                    coord_sys_elem = root.find(_t(NS_MOJ, '座標系'))
                    if coord_sys_elem is not None and coord_sys_elem.text:
                        if '任意' in coord_sys_elem.text:
                            self.xml_bytes = raw
                            self._parse_root(root)
                            found = True
                            break

                if not found:
                    raise ValueError(
                        "ZIP内に任意座標系のXMLファイルが見つかりません\n"
                        "（対象: <座標系>任意座標系</座標系> を含むXML）"
                    )
        else:
            with open(file_path, 'rb') as f:
                raw = f.read()
            try:
                root = _safe_fromstring(raw)
            except ET.ParseError as e:
                raise ValueError(f"XML解析エラー: {e}")

            coord_sys_elem = root.find(_t(NS_MOJ, '座標系'))
            if coord_sys_elem is None or not coord_sys_elem.text:
                raise ValueError("座標系の記述が見つかりません")
            if '任意' not in coord_sys_elem.text:
                raise ValueError(
                    f"このXMLは任意座標系ではありません（座標系: {coord_sys_elem.text}）\n"
                    "本プラグインは任意座標系のみを対象としています"
                )
            self.xml_bytes = raw
            self._parse_root(root)

    def _parse_root(self, root):
        """ルート要素から全データを解析する"""
        # --- メタデータ ---
        self.meta = {
            '地図名': _txt(root, _t(NS_MOJ, '地図名')),
            '市区町村コード': _txt(root, _t(NS_MOJ, '市区町村コード')),
            '市区町村名': _txt(root, _t(NS_MOJ, '市区町村名')),
            '座標系': _txt(root, _t(NS_MOJ, '座標系')),
        }

        # --- 空間属性 ---
        spatial_attr = root.find(_t(NS_MOJ, '空間属性'))
        if spatial_attr is None:
            raise ValueError("空間属性要素が見つかりません")

        self._parse_points(spatial_attr)
        self._parse_curves(spatial_attr)
        self._parse_surfaces(spatial_attr)

        # --- 主題属性 ---
        theme_attr = root.find(_t(NS_MOJ, '主題属性'))
        if theme_attr is None:
            raise ValueError("主題属性要素が見つかりません")

        self._parse_fude(theme_attr)

        # --- 図郭 ---
        self._parse_zukaku(root)

    def _swap_xy(self, x_str, y_str):
        """
        日本測量座標のX,Y → 表示座標のx,y へ変換
        XMLのX = 縦（南北）方向、XMLのY = 横（東西）方向
        → 表示上は x=横, y=縦 なので swap する
        """
        try:
            xml_x = float(x_str)
            xml_y = float(y_str)
            return (xml_y, xml_x)  # x_disp = xml_Y, y_disp = xml_X
        except (ValueError, TypeError):
            return (0.0, 0.0)

    def _parse_points(self, spatial_attr):
        """GM_Point を解析して points ディクショナリに格納"""
        for pt in spatial_attr.findall(_t(NS_ZMN, 'GM_Point')):
            pid = pt.get('id')
            if not pid:
                continue
            pos = pt.find(
                f'{_t(NS_ZMN, "GM_Point.position")}/'
                f'{_t(NS_ZMN, "DirectPosition")}'
            )
            if pos is not None:
                x_elem = pos.find(_t(NS_ZMN, 'X'))
                y_elem = pos.find(_t(NS_ZMN, 'Y'))
                x_str = x_elem.text if x_elem is not None else '0'
                y_str = y_elem.text if y_elem is not None else '0'
                self.points[pid] = self._swap_xy(x_str, y_str)

    def _parse_curves(self, spatial_attr):
        """
        GM_Curve を解析して curves ディクショナリに格納。
        座標の格納形式は2種類あるため両方対応する:
          1) GM_Position.direct  : X,Y値を直接記述
          2) GM_Position.indirect: GM_PointRef.point の idref でGM_Pointを参照
        """
        for curve in spatial_attr.findall(_t(NS_ZMN, 'GM_Curve')):
            cid = curve.get('id')
            if not cid:
                continue

            orient_elem = curve.find(_t(NS_ZMN, 'GM_OrientablePrimitive.orientation'))
            orientation = orient_elem.text.strip() if orient_elem is not None and orient_elem.text else '+'

            pts = []
            for ls in curve.findall(f'.//{_t(NS_ZMN, "GM_LineString")}'):
                for col in ls.findall(
                    f'{_t(NS_ZMN, "GM_LineString.controlPoint")}/'
                    f'{_t(NS_ZMN, "GM_PointArray.column")}'
                ):
                    # --- 形式1: GM_Position.direct（直接座標） ---
                    pos_direct = col.find(_t(NS_ZMN, 'GM_Position.direct'))
                    if pos_direct is not None:
                        x_elem = pos_direct.find(_t(NS_ZMN, 'X'))
                        y_elem = pos_direct.find(_t(NS_ZMN, 'Y'))
                        x_str = x_elem.text if x_elem is not None else '0'
                        y_str = y_elem.text if y_elem is not None else '0'
                        pts.append(self._swap_xy(x_str, y_str))
                        continue

                    # --- 形式2: GM_Position.indirect（GM_Pointへの参照） ---
                    pos_indirect = col.find(_t(NS_ZMN, 'GM_Position.indirect'))
                    if pos_indirect is not None:
                        ref_elem = pos_indirect.find(_t(NS_ZMN, 'GM_PointRef.point'))
                        if ref_elem is not None:
                            pt_idref = ref_elem.get('idref')
                            if pt_idref and pt_idref in self.points:
                                pts.append(self.points[pt_idref])

            if orientation == '-':
                pts = list(reversed(pts))

            self.curves[cid] = pts

    def _parse_surfaces(self, spatial_attr):
        """GM_Surface を解析して surfaces ディクショナリに格納"""
        for surf in spatial_attr.findall(_t(NS_ZMN, 'GM_Surface')):
            sid = surf.get('id')
            if not sid:
                continue
            curve_ids = []
            for gen in surf.findall(
                f'.//{_t(NS_ZMN, "GM_CompositeCurve.generator")}'
            ):
                cid_ref = gen.get('idref')
                if cid_ref:
                    curve_ids.append(cid_ref)
            self.surfaces[sid] = curve_ids

    def _parse_fude(self, theme_attr):
        """筆（土地パーセル）を解析"""
        self.fude_list = []
        self.fude_by_id = {}

        for fude in theme_attr.findall(_t(NS_MOJ, '筆')):
            fid = fude.get('id', '')
            oaza_name = _txt(fude, _t(NS_MOJ, '大字名'))
            koaza_name = _txt(fude, _t(NS_MOJ, '小字名'))
            chiban_val = _txt(fude, _t(NS_MOJ, '地番'))
            shape_ref = fude.find(_t(NS_MOJ, '形状'))
            surface_id = shape_ref.get('idref') if shape_ref is not None else None
            coord_type = _txt(fude, _t(NS_MOJ, '座標値種別'))

            entry = {
                'id': fid,
                '大字名': oaza_name,
                '小字名': koaza_name,
                '地番': chiban_val,
                'surface_id': surface_id,
                '座標値種別': coord_type,
            }
            self.fude_list.append(entry)
            self.fude_by_id[fid] = entry

    def _parse_zukaku(self, root):
        """図郭を解析"""
        self.zukaku_list = []
        for zg in root.findall(_t(NS_MOJ, '図郭')):
            map_number = _txt(zg, _t(NS_MOJ, '地図番号'))

            def get_corner(tag_name):
                elem = zg.find(_t(NS_MOJ, tag_name))
                if elem is not None:
                    x_e = elem.find(_t(NS_ZMN, 'X'))
                    y_e = elem.find(_t(NS_ZMN, 'Y'))
                    if x_e is not None and y_e is not None:
                        return self._swap_xy(x_e.text or '0', y_e.text or '0')
                return None

            fude_refs = []
            for ref in zg.findall(_t(NS_MOJ, '筆参照')):
                idref = ref.get('idref')
                if idref:
                    fude_refs.append(idref)

            self.zukaku_list.append({
                '地図番号': map_number,
                '左下座標': get_corner('左下座標'),
                '左上座標': get_corner('左上座標'),
                '右下座標': get_corner('右下座標'),
                '右上座標': get_corner('右上座標'),
                '筆参照_ids': fude_refs,
            })

    # --- ユーティリティ ---

    def get_oaza_list(self):
        """ユニークな大字名リストを返す（ソート済み）"""
        names = sorted(set(f['大字名'] for f in self.fude_list if f['大字名']))
        return names

    def get_koaza_list(self, oaza_name=None):
        """指定大字名に属するユニークな小字名リストを返す"""
        if oaza_name:
            names = sorted(set(
                f['小字名'] for f in self.fude_list
                if f['大字名'] == oaza_name and f['小字名']
            ))
        else:
            names = sorted(set(f['小字名'] for f in self.fude_list if f['小字名']))
        return names

    def get_chiban_list(self, oaza_name=None, koaza_name=None):
        """指定大字・小字に属する地番リストを返す（ソート済み）"""
        result = []
        for f in self.fude_list:
            if oaza_name and f['大字名'] != oaza_name:
                continue
            if koaza_name and f['小字名'] != koaza_name:
                continue
            if f['地番']:
                result.append(f['地番'])
        # 数値的ソート（枝番対応）
        def sort_key(s):
            parts = s.replace('-', '.').split('.')
            key = []
            for p in parts:
                try:
                    key.append((0, int(p)))
                except ValueError:
                    key.append((1, p))
            return key
        return sorted(result, key=sort_key)

    def get_fude_by_oaza_koaza_chiban(self, oaza_name, koaza_name, chiban_list):
        """
        大字名・小字名(任意)・地番リストに合致する筆リストを返す。
        koaza_name=None のとき小字フィルタをかけない（大字名+地番のみで検索）。
        """
        result = []
        for f in self.fude_list:
            if f['大字名'] != oaza_name:
                continue
            if koaza_name is not None and f['小字名'] != koaza_name:
                continue
            if f['地番'] in chiban_list:
                result.append(f)
        return result

    def get_zukaku_for_fude_ids(self, fude_id_set):
        """筆IDセットを含む図郭リストを返す"""
        result = []
        for zg in self.zukaku_list:
            refs = set(zg['筆参照_ids'])
            if refs & fude_id_set:
                result.append(zg)
        return result

    def build_polygon_coords(self, surface_id):
        """
        GM_Surface から座標リストを構築して返す。
        戻り値: [(x, y), ...] （閉じたリング）
        """
        if surface_id not in self.surfaces:
            return []

        curve_ids = self.surfaces[surface_id]
        if not curve_ids:
            return []

        all_pts = []
        for cid in curve_ids:
            if cid not in self.curves:
                continue
            pts = list(self.curves[cid])
            if not pts:
                continue
            if all_pts:
                # 先頭点が前の終点と重複していたら除去
                if pts[0] == all_pts[-1]:
                    pts = pts[1:]
            all_pts.extend(pts)

        if len(all_pts) < 3:
            return []

        # ポリゴンを閉じる
        if all_pts[0] != all_pts[-1]:
            all_pts.append(all_pts[0])

        return all_pts

    def get_centroid(self, coords):
        """ポリゴン座標の重心を返す"""
        if not coords:
            return (0.0, 0.0)
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def get_all_fude_in_zukaku(self, zukaku_list):
        """図郭リストに含まれる全筆を返す（重複なし）"""
        fude_ids = set()
        for zg in zukaku_list:
            for fid in zg['筆参照_ids']:
                fude_ids.add(fid)
        result = []
        seen = set()
        for fid in fude_ids:
            if fid in self.fude_by_id and fid not in seen:
                result.append(self.fude_by_id[fid])
                seen.add(fid)
        return result

    def generate_transformed_xml(self, transform_func):
        """
        変換済み座標を用いた新しいXMLバイト列を生成する。
        transform_func: (x_disp, y_disp) -> (X_plane, Y_plane)
        戻り値: bytes
        """
        if self.xml_bytes is None:
            raise ValueError("XMLデータが読み込まれていません")

        root = _safe_fromstring(self.xml_bytes)

        # 座標系タグを更新
        coord_sys_elem = root.find(_t(NS_MOJ, '座標系'))
        if coord_sys_elem is not None:
            coord_sys_elem.text = '平面直角座標系'

        # 空間属性内の座標を変換
        spatial_attr = root.find(_t(NS_MOJ, '空間属性'))
        if spatial_attr is not None:
            # GM_Point の座標変換
            for pt in spatial_attr.findall(_t(NS_ZMN, 'GM_Point')):
                pos = pt.find(
                    f'{_t(NS_ZMN, "GM_Point.position")}/'
                    f'{_t(NS_ZMN, "DirectPosition")}'
                )
                if pos is not None:
                    x_elem = pos.find(_t(NS_ZMN, 'X'))
                    y_elem = pos.find(_t(NS_ZMN, 'Y'))
                    if x_elem is not None and y_elem is not None:
                        try:
                            xml_x = float(x_elem.text)
                            xml_y = float(y_elem.text)
                            # swap して変換、結果を再swapしてXML形式で格納
                            disp_x = xml_y
                            disp_y = xml_x
                            plane_x, plane_y = transform_func(disp_x, disp_y)
                            # XMLのX=縦（平面直角のY）, XMLのY=横（平面直角のX）
                            x_elem.text = f'{plane_y:.3f}'
                            y_elem.text = f'{plane_x:.3f}'
                        except (ValueError, TypeError):
                            pass

            # GM_Curve 内の座標変換
            for pos in spatial_attr.findall(
                f'.//{_t(NS_ZMN, "GM_Position.direct")}'
            ):
                x_elem = pos.find(_t(NS_ZMN, 'X'))
                y_elem = pos.find(_t(NS_ZMN, 'Y'))
                if x_elem is not None and y_elem is not None:
                    try:
                        xml_x = float(x_elem.text)
                        xml_y = float(y_elem.text)
                        disp_x = xml_y
                        disp_y = xml_x
                        plane_x, plane_y = transform_func(disp_x, disp_y)
                        x_elem.text = f'{plane_y:.3f}'
                        y_elem.text = f'{plane_x:.3f}'
                    except (ValueError, TypeError):
                        pass

        # 図郭内の座標変換
        corner_tags = ['左下座標', '左上座標', '右下座標', '右上座標']
        for zg in root.findall(_t(NS_MOJ, '図郭')):
            for ctag in corner_tags:
                elem = zg.find(_t(NS_MOJ, ctag))
                if elem is not None:
                    x_elem = elem.find(_t(NS_ZMN, 'X'))
                    y_elem = elem.find(_t(NS_ZMN, 'Y'))
                    if x_elem is not None and y_elem is not None:
                        try:
                            xml_x = float(x_elem.text)
                            xml_y = float(y_elem.text)
                            disp_x = xml_y
                            disp_y = xml_x
                            plane_x, plane_y = transform_func(disp_x, disp_y)
                            x_elem.text = f'{plane_y:.3f}'
                            y_elem.text = f'{plane_x:.3f}'
                        except (ValueError, TypeError):
                            pass

        ET.register_namespace('', NS_MOJ)
        ET.register_namespace('zmn', NS_ZMN)
        ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        return ET.tostring(root, encoding='UTF-8', xml_declaration=True)
