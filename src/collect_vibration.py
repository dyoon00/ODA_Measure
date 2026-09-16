#!/usr/bin/env python3
"""
STM32U575 + IIS3DWB 진동 데이터 수집 스크립트 (OpenOCD Tcl RPC 기반)

- OpenOCD가 6666(Tcl RPC) 포트로 떠있어야 함:
    openocd -f interface/stlink.cfg -f target/stm32u5x.cfg

- ring_write_idx / ring_read_idx를 폴링해서 새 슬롯이 생기면
  dump_image로 x/y/z 배열을 읽어와서, 전력(collect_power.py)과 같은 방식으로
  여러 슬롯을 하나의 파일에 이어붙여 저장 (슬롯마다 새 파일 만들던 방식에서 변경).

260913: 파일 구조 변경 - SLOTS_PER_FILE(50슬롯=819200샘플)마다 파일 분할,
        슬롯마다 [타임스탬프(8B)] + [16384개 float32] 레코드로 이어쓰기.
        x/y/z는 MCU 메모리 자체가 분리되어 있으므로 여전히 별도 파일 3개로 유지.
"""

import socket
import os
import struct
import time
import argparse
import json


#---------오픈 OCD 설정-------------------------------
OPENOCD_HOST = 'localhost'
OPENOCD_PORT = 6666

# --------데이터 주소 (재빌드시 다시 할당해 주어야 함.까먹지 마라)---
ADDR_RING_X     = 0x200308E0
ADDR_RING_Y     = 0x200508E0
ADDR_RING_Z     = 0x200708E0
ADDR_WRITE_IDX  = 0x200A8C6C
ADDR_READ_IDX   = 0x200A8C70
ADDR_OVERRUN    = 0x200A8C74
ADDR_VIBE_STEP  = 0x20090C65   # Vibe_FFT_Step (uint8_t)

#--------- 데이터 크기관련, 링버퍼 상수 정의 -------------------
RING_SLOTS  = 2
FFT_LEN     = 16384
SLOT_BYTES  = FFT_LEN * 4   # float32 = 4바이트 (g단위, DC오프셋 제거 완료된 값)

# 260913: 전력(collect_power.py)의 SAMPLES_PER_FILE=819200과 동일한 기준으로 파일 분할
SAMPLES_PER_FILE = 819200
SLOTS_PER_FILE = SAMPLES_PER_FILE // FFT_LEN  # 50슬롯마다 파일 분할

SAVE_DIR = "./vibration_bin"
TMP_X = "/tmp/vib_x_tmp.bin"
TMP_Y = "/tmp/vib_y_tmp.bin"
TMP_Z = "/tmp/vib_z_tmp.bin"


class OpenOCD:
    def __init__(self, host=OPENOCD_HOST, port=OPENOCD_PORT):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port))

    def command(self, cmd):
        self.sock.sendall(cmd.encode() + b"\x1a")
        buf = b""
        while not buf.endswith(b"\x1a"):
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf[:-1].decode(errors="replace").strip()

    def read_u32(self, addr):
        response = self.command(f"read_memory 0x{addr:x} 32 1")
        return int(response.split()[0], 0)

    def read_u8(self, addr):
        response = self.command(f"read_memory 0x{addr:x} 8 1")
        return int(response.split()[0], 0)

    def write_u32(self, addr, value):
        self.command(f"write_memory 0x{addr:x} 32 {{{value}}}")

    def dump_image(self, filename, addr, size_bytes):
        # 260913: 이제 임시파일을 다시 읽어서 최종 파일에 이어붙여야 하므로,
        # 성공 여부를 확인해야 함 (collect_power.py의 dump_block과 동일한 방식)
        response = self.command(f"dump_image {filename} 0x{addr:x} {size_bytes}")
        if "dumped" not in response.lower() or "bytes" not in response.lower():
            return None
        if not os.path.exists(filename):
            return None
        with open(filename, "rb") as f:
            data = f.read()
        if len(data) != size_bytes:
            return None
        return data

    def close(self):
        self.sock.close()


def slot_address(base_addr, slot):
    return base_addr + slot * SLOT_BYTES


# 260913: 전력과 동일한 버그 수정 - 세션 시작 시각을 한 번만 고정하고,
# part 번호를 세션 동안 계속 증가시킴 (예전엔 매번 새 시각을 써서 항상 part001이었음)
_SESSION_TS = time.strftime("%Y%m%d_%H%M%S")
_part_idx = 0


def open_new_part_files():
    global _part_idx
    os.makedirs(SAVE_DIR, exist_ok=True)
    _part_idx += 1
    px = os.path.join(SAVE_DIR, f"vibration_{_SESSION_TS}_part{_part_idx:03d}_x.bin")
    py = os.path.join(SAVE_DIR, f"vibration_{_SESSION_TS}_part{_part_idx:03d}_y.bin")
    pz = os.path.join(SAVE_DIR, f"vibration_{_SESSION_TS}_part{_part_idx:03d}_z.bin")
    return open(px, "wb"), open(py, "wb"), open(pz, "wb"), (px, py, pz)


def write_slot_record(f, timestamp, data):
    # 슬롯 1개 레코드: [타임스탬프(8B, double)] + [16384개 float32]
    f.write(struct.pack("<d", timestamp))
    f.write(data)


def main():
    global SAVE_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=OPENOCD_HOST)
    parser.add_argument("--port", type=int, default=OPENOCD_PORT)
    parser.add_argument("--outdir", default=SAVE_DIR, help="bin 저장 폴더 (GUI가 측정명별 폴더를 지정할 때 사용)")
    args = parser.parse_args()
    SAVE_DIR = args.outdir

    ocd = OpenOCD(args.host, args.port)

    while ocd.read_u8(ADDR_VIBE_STEP) != 1:
        pass

    write_idx0 = ocd.read_u32(ADDR_WRITE_IDX)
    ocd.write_u32(ADDR_READ_IDX, write_idx0)
    print(f"[초기 동기화] write_idx0 = {write_idx0}")

    fx, fy, fz, paths = open_new_part_files()
    print(f"[파일 시작] {paths}")
    slots_in_file = 0

    slot_count = 0
    # 260913: 이 시점에 OpenOCD가 아직 준비 안 됐으면 read_u32가 예외를 던질 수 있으므로 재시도
    last_overrun = None
    while last_overrun is None:
        try:
            last_overrun = ocd.read_u32(ADDR_OVERRUN)
        except (IndexError, ValueError):
            time.sleep(0.1)
    # overrun_cnt도 MCU 리셋 전까지 계속 누적되는 값 -> 세션 시작 시점 기준값 별도 보관
    baseline_overrun = last_overrun
    status_path = os.path.join(SAVE_DIR, "vibration_status.json")

    try:
        while True:
            write_idx = ocd.read_u32(ADDR_WRITE_IDX)
            read_idx = ocd.read_u32(ADDR_READ_IDX)

            if write_idx > read_idx:
                for idx in range(read_idx, write_idx):
                    slot = idx % RING_SLOTS

                    data_x = ocd.dump_image(TMP_X, slot_address(ADDR_RING_X, slot), SLOT_BYTES)
                    data_y = ocd.dump_image(TMP_Y, slot_address(ADDR_RING_Y, slot), SLOT_BYTES)
                    data_z = ocd.dump_image(TMP_Z, slot_address(ADDR_RING_Z, slot), SLOT_BYTES)

                    if data_x is None or data_y is None or data_z is None:
                        print(f"[에러] 슬롯 리드 실패 (idx={idx}) - read_idx 전진 안 함, 재시도")
                        continue

                    timestamp = time.time()
                    write_slot_record(fx, timestamp, data_x)
                    write_slot_record(fy, timestamp, data_y)
                    write_slot_record(fz, timestamp, data_z)
                    fx.flush()
                    fy.flush()
                    fz.flush()

                    slot_count += 1
                    slots_in_file += 1

                    overrun = ocd.read_u32(ADDR_OVERRUN)
                    if overrun != last_overrun:
                        print(f"[오버런 발생!] idx={idx} overrun_cnt={last_overrun}->{overrun}")
                        last_overrun = overrun
                    if slot_count % 10 == 0:
                        d_overrun = overrun - baseline_overrun
                        print(f"[슬롯 {slot_count}] idx={idx} write_idx={write_idx} read_idx={read_idx} overrun_cnt(세션누적)={d_overrun}")
                        # GUI가 OpenOCD에 직접 접속 안 해도 되도록, 이미 읽은 값을 상태파일에도 씀
                        try:
                            with open(status_path, "w", encoding="utf-8") as sf:
                                json.dump({
                                    "overrun_session": d_overrun,
                                    "slot_count": slot_count,
                                    "updated_at": time.time(),
                                }, sf)
                        except Exception:
                            pass

                    if slots_in_file >= SLOTS_PER_FILE:
                        fx.close()
                        fy.close()
                        fz.close()
                        print(f"[파일 완료] {paths} ({slots_in_file}개 슬롯, {slots_in_file*FFT_LEN}샘플)")
                        fx, fy, fz, paths = open_new_part_files()
                        print(f"[파일 시작] {paths}")
                        slots_in_file = 0

                ocd.write_u32(ADDR_READ_IDX, write_idx)

    except KeyboardInterrupt:
        print("\n[중지됨]")
    finally:
        fx.close()
        fy.close()
        fz.close()
        ocd.close()


if __name__ == "__main__":
    main()
