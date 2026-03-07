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
coordinate_transform.py
座標変換モジュール（ヘルマート変換・アフィン変換）

ヘルマート変換（4パラメータ）: GCP 2点以上
アフィン変換（6パラメータ）  : GCP 3点以上（精度向上）
自動選択: GCP数が2点ならヘルマート、3点以上ならアフィン
"""

import math


def _check_numpy():
    """numpy の利用可否を確認"""
    try:
        import numpy as np
        return np, True
    except ImportError:
        return None, False


# ============================================================
# ヘルマート変換（Helmert / 相似変換）
# X = a*x - b*y + tx
# Y = b*x + a*y + ty
# a = s*cos(θ), b = s*sin(θ)
# ============================================================

def helmert_least_squares(src_pts, dst_pts):
    """
    ヘルマート変換パラメータを最小二乗法で算出する（numpy使用）。

    Parameters
    ----------
    src_pts : list of (x, y)  任意座標
    dst_pts : list of (X, Y)  平面直角座標

    Returns
    -------
    params : dict  変換パラメータ
    transform_func : callable (x, y) -> (X, Y)
    rmse : float  残差RMS誤差（メートル相当）
    """
    np, ok = _check_numpy()
    if not ok:
        return _helmert_manual(src_pts, dst_pts)

    n = len(src_pts)
    if n < 2:
        raise ValueError("ヘルマート変換には最低2点のGCPが必要です")

    A = np.zeros((2 * n, 4))
    b_vec = np.zeros(2 * n)

    for i, ((x, y), (X, Y)) in enumerate(zip(src_pts, dst_pts)):
        A[2*i,   :] = [ x, -y, 1, 0]
        A[2*i+1, :] = [ y,  x, 0, 1]
        b_vec[2*i]   = X
        b_vec[2*i+1] = Y

    result, residuals, rank, sv = np.linalg.lstsq(A, b_vec, rcond=None)
    a_param, b_param, tx, ty = result

    scale = math.sqrt(a_param**2 + b_param**2)
    rotation_deg = math.degrees(math.atan2(b_param, a_param))

    params = {
        'method': 'helmert',
        'a': float(a_param),
        'b': float(b_param),
        'tx': float(tx),
        'ty': float(ty),
        'scale': scale,
        'rotation_deg': rotation_deg,
    }

    def transform_func(x, y):
        X = a_param * x - b_param * y + tx
        Y = b_param * x + a_param * y + ty
        return float(X), float(Y)

    # RMSE算出
    rmse = _calc_rmse(src_pts, dst_pts, transform_func)
    params['rmse'] = rmse

    return params, transform_func, rmse


def _helmert_manual(src_pts, dst_pts):
    """numpy非依存のヘルマート変換（2点の場合のみ正確）"""
    n = len(src_pts)
    # 重心を使った正規化
    cx_s = sum(p[0] for p in src_pts) / n
    cy_s = sum(p[1] for p in src_pts) / n
    cx_d = sum(p[0] for p in dst_pts) / n
    cy_d = sum(p[1] for p in dst_pts) / n

    sum_xx_yy = sum((p[0]-cx_s)**2 + (p[1]-cy_s)**2 for p in src_pts)
    if sum_xx_yy == 0:
        raise ValueError("GCP座標が全て同一点です")

    a_param = sum(
        (s[0]-cx_s) * (d[0]-cx_d) + (s[1]-cy_s) * (d[1]-cy_d)
        for s, d in zip(src_pts, dst_pts)
    ) / sum_xx_yy

    b_param = sum(
        (s[0]-cx_s) * (d[1]-cy_d) - (s[1]-cy_s) * (d[0]-cx_d)
        for s, d in zip(src_pts, dst_pts)
    ) / sum_xx_yy

    tx = cx_d - a_param * cx_s + b_param * cy_s
    ty = cy_d - b_param * cx_s - a_param * cy_s

    scale = math.sqrt(a_param**2 + b_param**2)
    rotation_deg = math.degrees(math.atan2(b_param, a_param))

    params = {
        'method': 'helmert',
        'a': a_param,
        'b': b_param,
        'tx': tx,
        'ty': ty,
        'scale': scale,
        'rotation_deg': rotation_deg,
    }

    def transform_func(x, y):
        X = a_param * x - b_param * y + tx
        Y = b_param * x + a_param * y + ty
        return float(X), float(Y)

    rmse = _calc_rmse(src_pts, dst_pts, transform_func)
    params['rmse'] = rmse
    return params, transform_func, rmse


# ============================================================
# アフィン変換（6パラメータ）
# X = a1*x + a2*y + a3
# Y = b1*x + b2*y + b3
# ============================================================

def affine_least_squares(src_pts, dst_pts):
    """
    アフィン変換パラメータを最小二乗法で算出する。

    Parameters
    ----------
    src_pts : list of (x, y)  任意座標
    dst_pts : list of (X, Y)  平面直角座標

    Returns
    -------
    params : dict
    transform_func : callable
    rmse : float
    """
    np, ok = _check_numpy()
    if not ok:
        raise RuntimeError(
            "アフィン変換にはnumpyが必要です。\n"
            "QGIS Python環境にnumpyが含まれているか確認してください"
        )

    n = len(src_pts)
    if n < 3:
        raise ValueError("アフィン変換には最低3点のGCPが必要です")

    A = np.zeros((2 * n, 6))
    b_vec = np.zeros(2 * n)

    for i, ((x, y), (X, Y)) in enumerate(zip(src_pts, dst_pts)):
        A[2*i,   :] = [x, y, 1, 0, 0, 0]
        A[2*i+1, :] = [0, 0, 0, x, y, 1]
        b_vec[2*i]   = X
        b_vec[2*i+1] = Y

    result, residuals, rank, sv = np.linalg.lstsq(A, b_vec, rcond=None)
    a1, a2, a3, b1, b2, b3 = result

    params = {
        'method': 'affine',
        'a1': float(a1), 'a2': float(a2), 'a3': float(a3),
        'b1': float(b1), 'b2': float(b2), 'b3': float(b3),
    }

    def transform_func(x, y):
        X = a1 * x + a2 * y + a3
        Y = b1 * x + b2 * y + b3
        return float(X), float(Y)

    rmse = _calc_rmse(src_pts, dst_pts, transform_func)
    params['rmse'] = rmse

    return params, transform_func, rmse


def _calc_rmse(src_pts, dst_pts, transform_func):
    """残差RMS誤差を計算"""
    if not src_pts:
        return 0.0
    sq_sum = 0.0
    for (x, y), (X, Y) in zip(src_pts, dst_pts):
        Xp, Yp = transform_func(x, y)
        sq_sum += (Xp - X)**2 + (Yp - Y)**2
    return math.sqrt(sq_sum / len(src_pts))


def auto_transform(src_pts, dst_pts, force_method=None):
    """
    GCP点数に応じて最適な変換を自動選択する。

    force_method: None（自動）, 'helmert', 'affine'

    Returns
    -------
    params, transform_func, rmse
    """
    n = len(src_pts)
    if n < 2:
        raise ValueError("最低2点のGCPが必要です")

    if force_method == 'helmert':
        return helmert_least_squares(src_pts, dst_pts)
    elif force_method == 'affine':
        if n < 3:
            raise ValueError("アフィン変換には最低3点のGCPが必要です")
        return affine_least_squares(src_pts, dst_pts)
    else:
        # 自動選択
        if n == 2:
            return helmert_least_squares(src_pts, dst_pts)
        else:
            # 3点以上: アフィンを試みてフォールバック
            try:
                return affine_least_squares(src_pts, dst_pts)
            except Exception:
                return helmert_least_squares(src_pts, dst_pts)


def format_params(params):
    """変換パラメータを人間が読みやすい文字列にフォーマット"""
    lines = []
    method = params.get('method', '')

    if method == 'helmert':
        lines.append("【変換方式】ヘルマート変換（相似変換・4パラメータ）")
        lines.append(f"  縮尺係数 : {params.get('scale', 0):.8f}")
        lines.append(f"  回転角度 : {params.get('rotation_deg', 0):.6f}°")
        lines.append(f"  並進X    : {params.get('tx', 0):.3f} m")
        lines.append(f"  並進Y    : {params.get('ty', 0):.3f} m")
    elif method == 'affine':
        lines.append("【変換方式】アフィン変換（6パラメータ最小二乗）")
        lines.append(f"  a1={params.get('a1',0):.8f}, a2={params.get('a2',0):.8f}, a3={params.get('a3',0):.3f}")
        lines.append(f"  b1={params.get('b1',0):.8f}, b2={params.get('b2',0):.8f}, b3={params.get('b3',0):.3f}")

    rmse = params.get('rmse', None)
    if rmse is not None:
        lines.append(f"  残差RMSE : {rmse:.4f} (座標単位)")

    return '\n'.join(lines)
