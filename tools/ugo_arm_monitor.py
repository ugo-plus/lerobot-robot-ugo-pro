#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ugo_arm_monitor.py

ugo アームモニター（MCU側）→ PC のUDP送信を受け、
各サーボの「現在角度/現在速度/現在トルク」を標準出力へ最新状態で描画する

MCU v1.0 / v1.1 両対応:
  - v1.0: `vsd` パケット（フォロワーデータのみ）
  - v1.1: `vsd_l` パケット（リーダーデータ）、`vsd_f` パケット（フォロワーデータ）

既定:
  - 受信ホスト: 0.0.0.0（全IF）
  - 受信ポート: 8886  （資料のPC側固定ポート）
  - 画面更新:  20Hz

資料の通信仕様（固定IP、ポート、CSVの行形式など）に準拠。
"""

import argparse
import socket
import sys
import time
from typing import Dict, List, Optional


# ---- データ保持用 -----------------------------------------------------------
class ServoState:
    def __init__(self, source: str = "follower"):
        self.source = source  # "leader" or "follower"
        # サーボIDの昇順リスト
        self.ids: List[int] = []
        # 各系列の最新値（id -> 値）
        self.agl: Dict[int, float] = {}  # 0.1度単位 → 表示は度に換算
        self.vel: Dict[int, int] = {}  # 生値
        self.cur: Dict[int, int] = {}  # 生値
        # その他（必要なら拡張）
        self.obj: Dict[int, float] = {}
        # 最終更新時刻
        self.last_update: Optional[float] = None

    def set_ids(self, ids: List[int]):
        # 空値初期化はせず、既存値は温存。表示時に存在チェック。
        self.ids = sorted(ids)

    def _upsert_series(self, name: str, values: List[str]):
        # 現在のID順に対応する値群が来る前提
        if not self.ids or len(values) < len(self.ids):
            return
        self.last_update = time.time()
        if name == "agl":
            for sid, v in zip(self.ids, values[: len(self.ids)]):
                try:
                    # 0.1度単位 → 度
                    self.agl[sid] = float(v) / 10.0
                except ValueError:
                    pass
        elif name == "vel":
            for sid, v in zip(self.ids, values[: len(self.ids)]):
                try:
                    self.vel[sid] = int(float(v))
                except ValueError:
                    pass
        elif name == "cur":
            for sid, v in zip(self.ids, values[: len(self.ids)]):
                try:
                    self.cur[sid] = int(float(v))
                except ValueError:
                    pass
        elif name == "obj":
            for sid, v in zip(self.ids, values[: len(self.ids)]):
                try:
                    self.obj[sid] = float(v) / 10.0
                except ValueError:
                    pass


class MonitorState:
    """MCU v1.0/v1.1 両対応のモニター状態管理"""

    def __init__(self):
        self.follower = ServoState(source="follower")
        self.leader = ServoState(source="leader")
        self.mcu_version: str = "unknown"
        self.current_target: Optional[ServoState] = None

    def detect_version(self, packet_type: str) -> None:
        """パケットタイプからMCUバージョンを検出"""
        if packet_type in ("vsd_l", "vsd_f"):
            self.mcu_version = "v1.1"
        elif packet_type == "vsd" and self.mcu_version == "unknown":
            self.mcu_version = "v1.0"

    def has_leader_data(self) -> bool:
        return self.leader.last_update is not None

    def get_all_ids(self) -> List[int]:
        """リーダーとフォロワーの全IDを統合して返す"""
        all_ids = set(self.follower.ids) | set(self.leader.ids)
        return sorted(all_ids)


# ---- パーサ -----------------------------------------------------------------
def parse_and_update(line: str, state: MonitorState) -> None:
    """
    1行CSVを解釈して state を更新。

    MCU v1.0:
      vsd,,ver:251008, interval:47[ms], read:31[ms], write:13[ms], mode:bilateral(1)
      id,11,12,13,...
      agl,123,456,...
      vel,0,0,...
      cur,0,0,...
      obj,0,0,...

    MCU v1.1:
      vsd_l,,ver:260323, interval:47[ms], ...  (リーダーデータ)
      id,11,12,13,...
      agl,100,200,...
      ...
      vsd_f,,ver:260323, interval:47[ms], ...  (フォロワーデータ)
      id,11,12,13,...
      agl,90,180,...
      ...
    """
    line = line.strip()
    if not line:
        return

    parts = [p.strip() for p in line.split(",")]
    head = parts[0] if parts else ""

    # MCU v1.1: リーダーデータパケットヘッダ
    if head == "vsd_l":
        state.detect_version("vsd_l")
        state.current_target = state.leader
        return

    # MCU v1.1: フォロワーデータパケットヘッダ
    if head == "vsd_f":
        state.detect_version("vsd_f")
        state.current_target = state.follower
        return

    # MCU v1.0: 従来のvsdパケットヘッダ（フォロワーのみ）
    if head == "vsd":
        state.detect_version("vsd")
        state.current_target = state.follower
        return

    # パケットヘッダを受信していない場合は無視
    if state.current_target is None:
        state.current_target = state.follower  # デフォルトはフォロワー

    target = state.current_target

    # データ行
    key = head
    values = parts[1:]

    if key == "id":
        # 数値のみ抽出（万一コメントが混ざっても耐性を持たせる）
        ids = []
        for v in values:
            try:
                ids.append(int(v))
            except ValueError:
                # コメント等は読み飛ばし
                pass
        if ids:
            target.set_ids(ids)
    elif key in ("agl", "vel", "cur", "obj"):
        target._upsert_series(key, values)
    else:
        # 未知キーは無視
        pass


# ---- レンダラ ---------------------------------------------------------------
def render(state: MonitorState, last_rx_ts: Optional[float], show_obj: bool = False):
    """
    端末へ上書き描画。
    MCU v1.1の場合はリーダーとフォロワーを横並びで表示。
    """
    # 画面クリア & カーソル先頭
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.write("ugo arm UDP Monitor |  Ctrl+C to exit\n")
    sys.stdout.write(f"MCU Version: {state.mcu_version}\n")

    if last_rx_ts:
        age = time.time() - last_rx_ts
        sys.stdout.write(
            f"Last packet: {time.strftime('%Y-%m-%d %H:%M:%S')}  (age: {age:.2f}s)\n"
        )
    else:
        sys.stdout.write("Last packet: (waiting...)\n")

    sys.stdout.write("\n")

    # MCU v1.1: リーダーとフォロワーを横並びで表示
    if state.has_leader_data():
        render_v1_1(state)
    else:
        # MCU v1.0: フォロワーのみ表示
        render_v1_0(state, show_obj)

    sys.stdout.flush()


def render_v1_0(state: MonitorState, show_obj: bool = False):
    """MCU v1.0 用の表示（フォロワーのみ）"""
    follower = state.follower

    if not follower.ids:
        sys.stdout.write("Waiting for 'id, ...' line to define servo ordering...\n")
        return

    # ヘッダ
    if show_obj:
        sys.stdout.write(
            f"{'ID':>4} | {'Angle[deg]':>11} | {'Obj[deg]':>11} | "
            f"{'Vel(raw)':>9} | {'Cur(raw)':>9}\n"
        )
        sys.stdout.write("-" * 60 + "\n")
    else:
        sys.stdout.write(
            f"{'ID':>4} | {'Angle[deg]':>11} | {'Vel(raw)':>9} | {'Cur(raw)':>9}\n"
        )
        sys.stdout.write("-" * 45 + "\n")

    for sid in follower.ids:
        ang = follower.agl.get(sid, float("nan"))
        vel = follower.vel.get(sid, 0)
        cur = follower.cur.get(sid, 0)
        if show_obj:
            obj = follower.obj.get(sid, float("nan"))
            sys.stdout.write(
                f"{sid:>4} | {ang:>11.1f} | {obj:>11.1f} | {vel:>9} | {cur:>9}\n"
            )
        else:
            sys.stdout.write(f"{sid:>4} | {ang:>11.1f} | {vel:>9} | {cur:>9}\n")


def render_v1_1(state: MonitorState):
    """MCU v1.1 用の表示（リーダー/フォロワー横並び）"""
    leader = state.leader
    follower = state.follower

    all_ids = state.get_all_ids()
    if not all_ids:
        sys.stdout.write("Waiting for 'id, ...' line to define servo ordering...\n")
        return

    # 右腕と左腕を分けて表示
    right_ids = [sid for sid in all_ids if 11 <= sid <= 18]
    left_ids = [sid for sid in all_ids if 21 <= sid <= 28]
    other_ids = [sid for sid in all_ids if sid not in right_ids and sid not in left_ids]

    def render_arm_section(ids: List[int], arm_name: str):
        if not ids:
            return

        sys.stdout.write(f"\n[{arm_name}]\n")
        # ヘッダ
        sys.stdout.write(
            f"{'ID':>4} | {'Leader':>10} | {'Follower':>10} | "
            f"{'Error':>8} | {'Vel':>6} | {'Cur':>6}\n"
        )
        sys.stdout.write("-" * 62 + "\n")

        for sid in ids:
            leader_ang = leader.agl.get(sid, float("nan"))
            follower_ang = follower.agl.get(sid, float("nan"))
            vel = follower.vel.get(sid, 0)
            cur = follower.cur.get(sid, 0)

            # リーダー角度
            if leader_ang == leader_ang:  # not NaN
                leader_str = f"{leader_ang:>10.1f}"
            else:
                leader_str = f"{'---':>10}"

            # フォロワー角度
            if follower_ang == follower_ang:  # not NaN
                follower_str = f"{follower_ang:>10.1f}"
            else:
                follower_str = f"{'---':>10}"

            # トラッキングエラー
            if leader_ang == leader_ang and follower_ang == follower_ang:
                error = leader_ang - follower_ang
                error_str = f"{error:>+8.1f}"
            else:
                error_str = f"{'---':>8}"

            sys.stdout.write(
                f"{sid:>4} | {leader_str} | {follower_str} | "
                f"{error_str} | {vel:>6} | {cur:>6}\n"
            )

    render_arm_section(right_ids, "Right Arm (11-18)")
    render_arm_section(left_ids, "Left Arm (21-28)")
    render_arm_section(other_ids, "Other")

    # サマリー統計
    sys.stdout.write("\n")
    sys.stdout.write("-" * 62 + "\n")

    # 最大トラッキングエラーを計算
    max_error = 0.0
    max_error_id = None
    for sid in all_ids:
        leader_ang = leader.agl.get(sid, float("nan"))
        follower_ang = follower.agl.get(sid, float("nan"))
        if leader_ang == leader_ang and follower_ang == follower_ang:
            error = abs(leader_ang - follower_ang)
            if error > max_error:
                max_error = error
                max_error_id = sid

    if max_error_id is not None:
        sys.stdout.write(
            f"Max tracking error: {max_error:.1f} deg (ID={max_error_id})\n"
        )
    else:
        sys.stdout.write("Max tracking error: N/A\n")


# ---- メイン -----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="V-Sido UDP listener (PC side)")
    ap.add_argument("--host", default="0.0.0.0", help="bind host (default: 0.0.0.0)")
    ap.add_argument(
        "--port", type=int, default=8886, help="bind UDP port (default: 8886)"
    )
    ap.add_argument(
        "--fps",
        type=float,
        default=20.0,
        help="display refresh rate in Hz (default: 20)",
    )
    ap.add_argument(
        "--show-obj",
        action="store_true",
        help="show target angle (obj) column (v1.0 only)",
    )
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 受信バッファ大きめ
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.bind((args.host, args.port))
    sock.settimeout(0.01)

    state = MonitorState()
    last_render = 0.0
    render_interval = 1.0 / max(1e-3, args.fps)
    last_rx_ts: Optional[float] = None
    partial_buf = ""  # パケット跨ぎの行連結用

    try:
        while True:
            # 受信（ノンブロック風）
            try:
                data, _ = sock.recvfrom(65535)
                last_rx_ts = time.time()
                text = data.decode("utf-8", errors="ignore")
                # 改行で分割、途中行はバッファリング
                text = partial_buf + text
                lines = text.splitlines(keepends=False)
                if text and not text.endswith("\n"):
                    # 最後の行は次パケットに続く可能性
                    partial_buf = lines.pop() if lines else text
                else:
                    partial_buf = ""
                for line in lines:
                    parse_and_update(line, state)
            except socket.timeout:
                pass

            # 一定周期で描画
            now = time.time()
            if now - last_render >= render_interval:
                render(state, last_rx_ts, show_obj=args.show_obj)
                last_render = now

    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
