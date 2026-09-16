import socket
import time
import os
import struct
import argparse
import json

# ==================== OpenOCD 연결 설정 (Tcl RPC 포트, 진동 프로젝트와 동일 방식) ====================
OPENOCD_HOST = "localhost"
OPENOCD_PORT = 6668  # 260911: 진동 원본 테스트 코드가 6666 하드코딩이라, 동시 실행 위해 전력은 6668로 분리

# ==================== 메모리 주소 (PowerMeasurePCB_MCU_DumpGather.elf, 260910 16:58 빌드 기준) ====================
G_BATCH_BUF_ADDR      = 0x200005ec
G_BATCH_HEAD_ADDR     = 0x200bdbec
G_BATCH_TAIL_ADDR     = 0x200bdbf0
G_OVERFLOW_COUNT_ADDR = 0x200bdbf4
MISSED_DRDY_ADDR      = 0x20000580

# ==================== 링버퍼 구조 (u_ads_bufCollect.h와 반드시 일치해야 함) ====================
BATCH_BANK_COUNT = 101
BATCH_SIZE       = 256   # 뱅크 1개당 프레임 수
FRAME_SIZE       = 30    # SPI 프레임 1개 크기(바이트): STATUS(3)+CH0~7(24)+CRC(3)
BANK_BYTES       = BATCH_SIZE * FRAME_SIZE  # 7680

# ==================== ADS131M08 스케일링 상수 (u_power_cal.h와 반드시 일치해야 함) ====================
ADS_VREF            = 1.2
ADS_GAIN            = 1.0
ADS_ADC_FS          = 16777216.0
ADS_VOLTAGE_DIVIDER = 1321.0
CT_RATIO            = 3000.0
R_BURDEN            = 12.98

V_LSB_SCALING     = (2.0 * ADS_VREF * ADS_VOLTAGE_DIVIDER) / (ADS_ADC_FS * ADS_GAIN)
I_LSB_SCALING_CT  = (2.0 * ADS_VREF * CT_RATIO) / (ADS_ADC_FS * ADS_GAIN * R_BURDEN)

# ==================== 파일 저장 설정 ====================
SAMPLES_PER_FILE = 819200
BANKS_PER_FILE = SAMPLES_PER_FILE // BATCH_SIZE  # 3200
OUTPUT_DIR = "./power_bin"
TMP_DUMP = "/tmp/power_bank_tmp.bin"

POLL_INTERVAL_SEC = 0.003
LOG_EVERY_N_BANKS = 620  # 대략 10초에 한 번 요약 로그


# ==================== OpenOCD Tcl RPC 통신 (vib_repo/collect_vibration.py와 동일 방식) ====================
def connect():
    # Tcl RPC는 텔넷과 달리 접속 시 배너가 없어서 별도로 비울 필요 없음
    return socket.create_connection((OPENOCD_HOST, OPENOCD_PORT), timeout=5)


def send_cmd(sock, cmd):
    # Tcl RPC는 명령 끝에 \x1a(Ctrl+Z)를 붙이고, 응답도 \x1a로 끝남 (프롬프트 추측 불필요)
    sock.sendall(cmd.encode() + b"\x1a")
    buf = b""
    while not buf.endswith(b"\x1a"):
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return buf[:-1].decode(errors="replace").strip()


def read_u32(sock, addr):
    resp = send_cmd(sock, f"read_memory 0x{addr:x} 32 1")
    try:
        return int(resp.split()[0], 0)
    except (IndexError, ValueError):
        return None


def write_u32(sock, addr, value):
    send_cmd(sock, f"write_memory 0x{addr:x} 32 {{{value}}}")


def dump_block(sock, addr, size, tmp_path):
    resp = send_cmd(sock, f"dump_image {tmp_path} 0x{addr:x} {size}")
    # 260911: "error" 문자열 유무로만 판단하면 실패를 놓침 (예: OpenOCD의
    # "couldn't open ..." 실패 메시지에는 "error"라는 단어가 없음). 성공 시에만
    # 나오는 "dumped ... bytes" 문구가 있는지로 판단하는 게 더 안전함.
    # (임시파일 재사용 + 크기체크로 어느정도 방어는 되지만, 이 체크가 1차 방어선)
    if "dumped" not in resp.lower() or "bytes" not in resp.lower():
        print(f"[진단] dump_image 실패 원본 응답: {resp!r}")
        return None
    if not os.path.exists(tmp_path):
        print(f"[진단] 임시파일 없음: {tmp_path}")
        return None
    with open(tmp_path, "rb") as f:
        data = f.read()
    if len(data) != size:
        print(f"[진단] 임시파일 크기 불일치: {len(data)} != {size}")
        return None
    return data


# ==================== 프레임 파싱 (ADS_AccData_In_FFTarray의 C 로직과 1:1 대응) ====================
def sign_extend_24(raw24):
    # C: int32_t raw = (b0<<24)|(b1<<16)|(b2<<8); raw >>= 8;  (부호확장 24비트 -> 32비트)
    if raw24 & 0x800000:
        raw24 -= 0x1000000
    return raw24


def parse_bank(bank_bytes):
    """
    bank_bytes: 7680바이트 (256프레임 x 30바이트)
    반환: 256개의 (V_R, V_S, V_T, I_R, I_S, I_T, I_N) 튜플 리스트 (스케일링 완료, float)

    채널 매핑(u_ads_bufCollect.c ADS_AccData_In_FFTarray 원본 로직과 동일):
      CH0=I Neutral, CH1=I Phase C, CH2=I Phase B, CH3=I Phase A
      CH4=V Phase C, CH5=V Phase B, CH6=V Phase A
      ch<4: i_out[3-ch],  4<=ch<7: v_out[6-ch]
    """
    out = []
    for frame in range(BATCH_SIZE):
        base = frame * FRAME_SIZE
        v = [0, 0, 0]  # v[0]=R, v[1]=S, v[2]=T
        i = [0, 0, 0, 0]  # i[0]=R, i[1]=S, i[2]=T, i[3]=N

        for ch in range(7):  # CH0~CH6만 사용 (원본과 동일, CH7/STATUS/CRC 미사용)
            off = base + 3 + ch * 3
            b0 = bank_bytes[off]
            b1 = bank_bytes[off + 1]
            b2 = bank_bytes[off + 2]
            raw24 = (b0 << 16) | (b1 << 8) | b2
            raw = sign_extend_24(raw24)

            if ch < 4:
                i[3 - ch] = raw
            else:
                v[6 - ch] = raw

        v_scaled = (v[0] * V_LSB_SCALING, v[1] * V_LSB_SCALING, v[2] * V_LSB_SCALING)
        i_scaled = (i[0] * I_LSB_SCALING_CT, i[1] * I_LSB_SCALING_CT,
                    i[2] * I_LSB_SCALING_CT, i[3] * I_LSB_SCALING_CT)

        out.append(v_scaled + i_scaled)  # (V_R,V_S,V_T,I_R,I_S,I_T,I_N)

    return out


# ==================== 파일 출력 ====================
# 260913: 버그 수정 - 예전엔 파일 새로 만들 때마다 time.strftime()을 다시 호출해서
# 매번 새 타임스탬프가 되는 바람에, "이미 있나?" 체크가 항상 통과해 part 번호가
# 절대 안 늘어나고 계속 part001로만 저장되던 문제가 있었음(is_first_part()가
# 모든 파일을 첫 파일로 오판 -> 메타데이터가 매 파일마다 들어감).
# 세션 시작 시각을 한 번만 고정하고, part 번호는 세션 동안 계속 증가시킴.
_SESSION_TS = time.strftime("%Y%m%d_%H%M%S")
_part_idx = 0


def open_new_part_file():
    global _part_idx
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _part_idx += 1
    path = os.path.join(OUTPUT_DIR, f"power_{_SESSION_TS}_part{_part_idx:03d}.bin")
    return open(path, "wb"), path


def write_bank_to_file(f, timestamp, parsed_frames):
    # 뱅크 1개 레코드: [타임스탬프(8B, double)] + [256프레임 x 7채널 float32]
    f.write(struct.pack("<d", timestamp))
    for row in parsed_frames:
        f.write(struct.pack("<7f", *row))


# ==================== 메인 루프 ====================
def main():
    global OUTPUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default=OUTPUT_DIR, help="bin 저장 폴더 (GUI가 측정명별 폴더를 지정할 때 사용)")
    args = parser.parse_args()
    OUTPUT_DIR = args.outdir

    sock = connect()
    print(f"[연결됨] OpenOCD Tcl RPC {OPENOCD_HOST}:{OPENOCD_PORT}")

    # 260913: 진동(collect_vibration.py)과 동일한 방식으로 변경 - 예전에 남아있던
    # g_batch_tail(묵은 backlog)부터 따라잡으려 하지 않고, "지금 이 순간의 head"로
    # 바로 동기화함. 예전 방식은 파이썬 실행 전까지 MCU가 이미 채워둔 backlog를
    # 시작하자마자 따라잡으려다가 오버런이 나는 원인이었음(실측으로 확인됨, 218뱅크).
    head0 = read_u32(sock, G_BATCH_HEAD_ADDR)
    while head0 is None:
        time.sleep(0.1)
        head0 = read_u32(sock, G_BATCH_HEAD_ADDR)
    local_tail = head0
    write_u32(sock, G_BATCH_TAIL_ADDR, local_tail)
    print(f"[초기 동기화] local_tail = head0 = {local_tail} (묵은 backlog 버림)")

    # 260913: overflow/missed_drdy는 MCU가 리셋되기 전까지 계속 누적되는 값이라,
    # 절대값이 아니라 "이 스크립트가 시작한 시점 대비 증가분"으로 GUI에 보여줘야 함.
    # (버그 수정: "or 0"으로 읽기실패를 조용히 0 취급하면, 이미 누적되어있던 큰 절대값이
    #  통째로 "이번 세션 유실"인 것처럼 잘못 표시됨 -> 제대로 읽힐 때까지 재시도)
    baseline_missed_drdy = read_u32(sock, MISSED_DRDY_ADDR)
    while baseline_missed_drdy is None:
        time.sleep(0.1)
        baseline_missed_drdy = read_u32(sock, MISSED_DRDY_ADDR)
    baseline_overflow = read_u32(sock, G_OVERFLOW_COUNT_ADDR)
    while baseline_overflow is None:
        time.sleep(0.1)
        baseline_overflow = read_u32(sock, G_OVERFLOW_COUNT_ADDR)
    status_path = os.path.join(OUTPUT_DIR, "power_status.json")

    f, path = open_new_part_file()
    print(f"[파일 시작] {path}")
    banks_in_file = 0
    bank_count = 0
    t_log_start = time.time()
    read_time_sum = 0.0
    read_time_max = 0.0

    try:
        while True:
            head = read_u32(sock, G_BATCH_HEAD_ADDR)
            if head is None:
                time.sleep(POLL_INTERVAL_SEC)
                continue

            if head <= local_tail:
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # 준비된 뱅크 1개를 읽음 (인덱스 = local_tail % BATCH_BANK_COUNT)
            bank_idx = local_tail % BATCH_BANK_COUNT
            bank_addr = G_BATCH_BUF_ADDR + bank_idx * BANK_BYTES

            t0 = time.time()
            raw_bank = dump_block(sock, bank_addr, BANK_BYTES, TMP_DUMP)
            t1 = time.time()

            if raw_bank is None:
                print(f"[에러] 뱅크 리드 실패 (idx={bank_idx}) - tail 전진 안 함, 재시도")
                continue

            # 읽기 완료 후에만 tail 전진 (MCU에 "이 뱅크 재사용해도 됨" 알림)
            local_tail += 1
            write_u32(sock, G_BATCH_TAIL_ADDR, local_tail)

            # 파싱 + 채널매핑 + 스케일링
            parsed = parse_bank(raw_bank)
            timestamp = time.time()
            write_bank_to_file(f, timestamp, parsed)
            f.flush()

            bank_count += 1
            banks_in_file += 1
            read_time_sum += (t1 - t0)
            read_time_max = max(read_time_max, t1 - t0)

            if bank_count % LOG_EVERY_N_BANKS == 0:
                missed_drdy = read_u32(sock, MISSED_DRDY_ADDR)
                overflow = read_u32(sock, G_OVERFLOW_COUNT_ADDR)
                d_missed = (missed_drdy - baseline_missed_drdy) if missed_drdy is not None else None
                d_overflow = (overflow - baseline_overflow) if overflow is not None else None
                elapsed = time.time() - t_log_start
                avg_read = (read_time_sum / LOG_EVERY_N_BANKS) * 1000
                print(
                    f"[뱅크 {bank_count:8d}] {elapsed:5.2f}s간 {LOG_EVERY_N_BANKS}뱅크 처리 "
                    f"평균읽기={avg_read:5.1f}ms 최대읽기={read_time_max*1000:5.1f}ms "
                    f"missed_drdy(세션누적)={d_missed} overflow(세션누적)={d_overflow} "
                    f"backlog={head - local_tail}"
                )
                # GUI가 OpenOCD에 직접 접속 안 해도 되도록, 이미 읽은 값을 상태파일에도 씀
                try:
                    with open(status_path, "w", encoding="utf-8") as sf:
                        json.dump({
                            "missed_drdy_session": d_missed,
                            "overflow_session": d_overflow,
                            "backlog": head - local_tail,
                            "bank_count": bank_count,
                            "updated_at": time.time(),
                        }, sf)
                except Exception:
                    pass
                t_log_start = time.time()
                read_time_sum = 0.0
                read_time_max = 0.0

            if banks_in_file >= BANKS_PER_FILE:
                f.close()
                print(f"[파일 완료] {path} ({banks_in_file}개 뱅크, {banks_in_file*BATCH_SIZE}샘플)")
                f, path = open_new_part_file()
                print(f"[파일 시작] {path}")
                banks_in_file = 0

    except KeyboardInterrupt:
        print("\n[중지됨]")
    finally:
        f.close()
        sock.close()


if __name__ == "__main__":
    main()
