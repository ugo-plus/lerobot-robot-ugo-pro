#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ugo_arm_monitor.py

ugo アームモニター（MCU側）→ PC のUDP送信を受け、
各サーボの「現在角度/現在速度/現在トルク」を標準出力へ最新状態で描画する

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
    def __init__(self):
        # サーボIDの昇順リスト
        self.ids: List[int] = []
        # 各系列の最新値（id -> 値）
        self.agl: Dict[int, float] = {}  # 0.1度単位 → 表示は度に換算
        self.vel: Dict[int, int]   = {}  # 生値
        self.cur: Dict[int, int]   = {}  # 生値
        # その他（必要なら拡張）
        self.onj_agl: Dict[int, float] = {}

    def set_ids(self, ids: List[int]):
        # 空値初期化はせず、既存値は温存。表示時に存在チェック。
        self.ids = sorted(ids)

    def _upsert_series(self, name: str, values: List[str]):
        # 現在のID順に対応する値群が来る前提
        if not self.ids or len(values) < len(self.ids):
            return
        if name == "agl":
            for sid, v in zip(self.ids, values[:len(self.ids)]):
                try:
                    # 0.1度単位 → 度
                    self.agl[sid] = float(v) / 10.0
                except ValueError:
                    pass
        elif name == "vel":
            for sid, v in zip(self.ids, values[:len(self.ids)]):
                try:
                    self.vel[sid] = int(float(v))
                except ValueError:
                    pass
        elif name == "cur":
            for sid, v in zip(self.ids, values[:len(self.ids)]):
                try:
                    self.cur[sid] = int(float(v))
                except ValueError:
                    pass
        elif name == "onj_agl":
            for sid, v in zip(self.ids, values[:len(self.ids)]):
                try:
                    self.onj_agl[sid] = float(v) / 10.0
                except ValueError:
                    pass

# ---- パーサ -----------------------------------------------------------------
def parse_and_update(line: str, state: ServoState):
    """
    1行CSVを解釈して state を更新。
    例:
      id,11,12,13,...
      agl,123,456,...
      vel,0,0,...
      cur,0,0,...
      vsd,interval:10[ms],...
    """
    line = line.strip()
    if not line:
        return

    parts = [p.strip() for p in line.split(",")]
    head = parts[0] if parts else ""
    # メタ行（vsd,interval...）は無視
    if head == "vsd":
        return

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
            state.set_ids(ids)
    elif key in ("agl", "vel", "cur", "onj_agl"):
        state._upsert_series(key, values)
    else:
        # 未知キーは無視
        pass

# ---- レンダラ ---------------------------------------------------------------
def render(state: ServoState, last_rx_ts: Optional[float]):
    """
    端末へ上書き描画（シンプルなテーブル）。
    """
    # 画面クリア & カーソル先頭
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.write("ugo arm UDP Monitor |  Ctrl+C to exit\n")
    if last_rx_ts:
        sys.stdout.write(f"Last packet: {time.strftime('%Y-%m-%d %H:%M:%S')}  (age: {time.time()-last_rx_ts:.2f}s)\n")
    else:
        sys.stdout.write("Last packet: (waiting...)\n")

    if not state.ids:
        sys.stdout.write("\nWaiting for 'id, ...' line to define servo ordering...\n")
        sys.stdout.flush()
        return

    # ヘッダ
    header = ["ID", "Angle[deg]", "Vel(raw)", "Torque(raw)"]
    sys.stdout.write("\n" + " | ".join(f"{h:>11}" for h in header) + "\n")
    sys.stdout.write("-" * (11*len(header) + 3*(len(header)-1)) + "\n")

    for sid in state.ids:
        ang = state.agl.get(sid, float("nan"))
        vel = state.vel.get(sid, 0)
        cur = state.cur.get(sid, 0)
        sys.stdout.write(f"{sid:>11d} | {ang:>11.1f} | {vel:>11d} | {cur:>11d}\n")

    # 補足（必要なら目標角度）
    # sys.stdout.write("\n(onj_agl available; hidden by default)\n")
    sys.stdout.flush()

# ---- メイン -----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="V-Sido UDP listener (PC side)")
    ap.add_argument("--host", default="0.0.0.0", help="bind host (default: 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8886, help="bind UDP port (default: 8886)")
    ap.add_argument("--fps", type=float, default=20.0, help="display refresh rate in Hz (default: 20)")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 受信バッファ大きめ
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.bind((args.host, args.port))
    sock.settimeout(0.01)

    state = ServoState()
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
                render(state, last_rx_ts)
                last_render = now

    except KeyboardInterrupt:
        print("\nbye.")

if __name__ == "__main__":
    main()


