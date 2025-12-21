# ugo_controller_mock.py
import argparse
import math
import random
import socket
import sys
import time
from typing import List


def parse_id_ranges(expr: str) -> List[int]:
    ids = []
    for part in expr.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            ids.extend(range(int(a), int(b) + 1))
        elif part:
            ids.append(int(part))
    return ids


def fmt_row(label: str, values: List[int]) -> str:
    cells = [f" {label}"]
    cells.extend(f"{v:4d}" if isinstance(v, int) else f"{v}" for v in values)
    return cells[0] + ", " + ", ".join(cells[1:])


def fmt_row_allow_blank(label: str, values: List[str]) -> str:
    cells = [f" {label}"]
    fmt_vals = []
    for v in values:
        if v == "":
            fmt_vals.append("   ")
        else:
            try:
                iv = int(v)
                fmt_vals.append(f"{iv:4d}")
            except ValueError:
                fmt_vals.append(v)
    return cells[0] + ", " + ", ".join(fmt_vals)


def build_vsd_line(ver: int, mode_str: str) -> str:
    interval = random.choice([44, 45, 46, 47, 48])
    read = random.choice([31, 32])
    write = random.choice([12, 13])
    return f"vsd, , ver:{ver}, interval:{interval}[ms], read:{read}[ms], write:{write}[ms], mode:{mode_str}"


def gen_agl_values(ids: List[int], t: float) -> List[int]:
    out = []
    for i, _ in enumerate(ids):
        amp_deg = 30.0 + 5.0 * math.sin(0.11 * i)
        freq = 0.25 + 0.02 * (i % 5)
        val_deg = amp_deg * math.sin(2 * math.pi * freq * t + i * 0.3)
        out.append(int(round(val_deg * 10)))
    return out


def gen_vel_values(ids: List[int], tick: int) -> List[int]:
    out = []
    for i, _ in enumerate(ids):
        if (tick + i) % random.choice([53, 97, 131]) == 0:
            out.append(random.choice([-50, 50]))
        else:
            out.append(0)
    return out


def gen_cur_values(ids: List[int]) -> List[int]:
    return [random.randint(-12, 12) for _ in ids]


def gen_obj_values(ids: List[int], style: str, flip: bool) -> List[int]:
    if style == "zero":
        return [0 for _ in ids]
    elif style == "sentinel":
        return [0 for _ in ids]
    else:
        return [0 if flip else 0 for _ in ids]


def maybe_drop_fields(values: List[int], drop_rate: float = 0.0) -> List[str]:
    out = []
    for v in values:
        if drop_rate > 0 and random.random() < drop_rate:
            out.append("")
        else:
            out.append(str(v))
    return out


def build_frame(ids, ver, mode_str, t, tick, obj_style, allow_blank_prob) -> str:
    vsd = build_vsd_line(ver, mode_str)
    row_id = fmt_row("id", ids)

    agl_vals = gen_agl_values(ids, t)
    vel_vals = gen_vel_values(ids, tick)
    cur_vals = gen_cur_values(ids)
    obj_vals = gen_obj_values(ids, obj_style, flip=((tick // 200) % 2 == 1))

    agl_s = fmt_row_allow_blank("agl", maybe_drop_fields(agl_vals, allow_blank_prob))
    vel_s = fmt_row("vel", vel_vals)
    cur_s = fmt_row("cur", cur_vals)
    obj_s = fmt_row("obj", obj_vals)
    return "\n".join([vsd, row_id, agl_s, vel_s, cur_s, obj_s])


def wait_for_trigger(host: str, port: int, timeout: float = None) -> tuple:
    """
    任意のUDPパケットを受信したら復帰。
    戻り値: (data, (sender_ip, sender_port))
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
    except OSError as e:
        print(f"[ERROR] trigger bind failed on {host}:{port}: {e}", file=sys.stderr)
        sys.exit(2)

    if timeout is not None:
        sock.settimeout(timeout)

    print(f"[INFO] waiting trigger on udp://{host}:{port} ...")
    try:
        data, addr = sock.recvfrom(4096)
        print(f"[INFO] trigger received from {addr}: {data[:60]!r}")
        return data, addr
    except socket.timeout:
        print("[WARN] trigger wait timed out.")
        sys.exit(3)
    finally:
        sock.close()


def main():
    ap = argparse.ArgumentParser(
        description="Dummy UDP VSD telemetry sender (MCU→PC emulator) with trigger"
    )
    ap.add_argument("--host", default="127.0.0.1", help="telemetry destination host")
    ap.add_argument("--port", type=int, default=8886, help="telemetry destination port")
    ap.add_argument("--pps", type=int, default=10, help="packets per second")
    ap.add_argument(
        "--ids",
        default="11-18,21-28",
        help="Servo id ranges (default RightArm 11-18, LeftArm 21-28).",
    )
    ap.add_argument("--ver", type=int, default=251008)
    ap.add_argument("--mode", choices=["bilateral", "normal"], default="bilateral")
    ap.add_argument(
        "--include-obj", choices=["zero", "sentinel", "auto"], default="sentinel"
    )
    ap.add_argument(
        "--blank-rate",
        type=float,
        default=0.0,
        help="agl 欠落フィールド発生確率（0.0-1.0）",
    )
    ap.add_argument("--trigger-host", default="0.0.0.0", help="trigger listen host")
    ap.add_argument(
        "--trigger-port", type=int, default=8888, help="trigger listen port"
    )
    ap.add_argument(
        "--trigger-timeout", type=float, default=None, help="seconds; None for infinite"
    )
    args = ap.parse_args()

    ids = parse_id_ranges(args.ids)
    if not ids:
        print("No servo IDs parsed. Check --ids.", file=sys.stderr)
        sys.exit(1)

    # --- 1) トリガ待ち ---
    _data, (trig_ip, trig_port) = wait_for_trigger(
        args.trigger_host, args.trigger_port, args.trigger_timeout
    )

    # --- 2) テレメトリ送信開始 ---
    dst = (args.host, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(
        f"[INFO] start sending telemetry to udp://{dst[0]}:{dst[1]}  pps={args.pps}  ids={ids}"
    )
    print(
        f"[INFO] mode= {args.mode}  ver={args.ver}  trigger_from={trig_ip}:{trig_port}"
    )

    mode_str = "bilateral(1)" if args.mode == "bilateral" else "nomal(0)"
    period = 1.0 / max(1, args.pps)
    t0 = time.perf_counter()
    tick = 0

    try:
        while True:
            now = time.perf_counter()
            t = now - t0

            obj_style = args.include_obj
            if obj_style == "auto":
                obj_style = "sentinel" if int(t) % 4 < 2 else "zero"

            frame = build_frame(
                ids=ids,
                ver=args.ver,
                mode_str=mode_str,
                t=t,
                tick=tick,
                obj_style=obj_style,
                allow_blank_prob=max(0.0, min(1.0, args.blank_rate)),
            )
            payload = (frame + "\n").encode("utf-8")
            sock.sendto(payload, dst)

            tick += 1
            next_deadline = t0 + (tick * period)
            sleep_s = next_deadline - time.perf_counter()
            if sleep_s > 0:
                time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\n[INFO] stopped by user (Ctrl+C).")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
