"""
collect_power.py로 저장한 .bin 파일을 읽어서:
  1. 뱅크 레코드를 연속된 시계열로 이어붙임
  2. 16384개(연속) 단위로 DC오프셋 제거 (윈도우 평균값 빼기)
  3. tab-separated CSV로 저장 (part001.csv에는 메타데이터 헤더 포함)

사용법:
  python3 post_process_power.py <입력.bin> [출력.csv] [--meta metadata.json]
"""
import sys
import struct
import argparse
import datetime
import numpy as np

from metadata_utils import load_metadata, write_metadata_header, is_first_part

BATCH_SIZE = 256
NUM_CHANNELS = 7  # V_R,V_S,V_T,I_R,I_S,I_T,I_N
BANK_RECORD_HEADER = 8  # 타임스탬프(double)
BANK_DATA_BYTES = BATCH_SIZE * NUM_CHANNELS * 4  # float32
BANK_RECORD_BYTES = BANK_RECORD_HEADER + BANK_DATA_BYTES

DC_WINDOW = 16384  # DC오프셋 제거 윈도우 크기 (연속 샘플 개수)

CHANNEL_NAMES = ["V_R", "V_S", "V_T", "I_R", "I_S", "I_T", "I_N"]


def read_bin_file(path):
    """뱅크 레코드들을 읽어서 (timestamps[nbanks], data[N,7]) 반환"""
    timestamps = []
    chunks = []

    with open(path, "rb") as f:
        while True:
            header = f.read(BANK_RECORD_HEADER)
            if len(header) < BANK_RECORD_HEADER:
                break  # 파일 끝
            (ts,) = struct.unpack("<d", header)

            body = f.read(BANK_DATA_BYTES)
            if len(body) < BANK_DATA_BYTES:
                print(f"[경고] 마지막 뱅크가 불완전함(파일이 도중에 잘림) - 버림")
                break

            arr = np.frombuffer(body, dtype="<f4").reshape(BATCH_SIZE, NUM_CHANNELS)
            timestamps.append(ts)
            chunks.append(arr)

    if not chunks:
        return np.array([]), np.zeros((0, NUM_CHANNELS), dtype=np.float32)

    data = np.concatenate(chunks, axis=0)  # (N, 7)
    return np.array(timestamps), data


def remove_dc_offset(data, window=DC_WINDOW):
    """연속된 window개 단위로 채널별 평균을 빼서 DC오프셋 제거 (in-place 아님, 새 배열 반환)"""
    n = data.shape[0]
    out = data.copy()

    for start in range(0, n, window):
        end = min(start + window, n)
        chunk = out[start:end]
        mean = chunk.mean(axis=0)  # 채널별 평균 (7,)
        out[start:end] = chunk - mean

    return out


def expand_timestamps(bank_timestamps):
    """뱅크별 타임스탬프를 각 샘플(256개)에 그대로 broadcast"""
    return np.repeat(bank_timestamps, BATCH_SIZE)


def format_timestamp(unix_ts):
    """260913 결정: bin에는 raw unix timestamp 그대로, CSV 변환시에만 사람이 읽는 형식으로"""
    return datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S.%f")


def write_csv(path, timestamps, data, meta, start_idx=0):
    with open(path, "w", encoding="utf-8") as f:
        if meta is not None:
            write_metadata_header(f, meta)
        f.write("idx\ttimestamp\t" + "\t".join(CHANNEL_NAMES) + "\n")
        n = data.shape[0]
        for i in range(n):
            row = data[i]
            f.write(
                f"{start_idx + i}\t{format_timestamp(timestamps[i])}\t" +
                "\t".join(f"{v:.6f}" for v in row) +
                "\n"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bin_path")
    parser.add_argument("csv_path", nargs="?", default=None)
    parser.add_argument("--meta", default=None, help="metadata.json 경로 (part001일 때만 헤더에 씀)")
    parser.add_argument("--start-idx", type=int, default=0, help="이 파일의 idx 시작값 (여러 part를 이어붙일 때 사용)")
    args = parser.parse_args()

    in_path = args.bin_path
    out_path = args.csv_path if args.csv_path else in_path.rsplit(".", 1)[0] + ".csv"

    print(f"[읽는 중] {in_path}")
    bank_ts, data = read_bin_file(in_path)
    if data.shape[0] == 0:
        print("[에러] 데이터가 없습니다.")
        sys.exit(1)

    print(f"[정보] 총 샘플수={data.shape[0]}, 뱅크수={len(bank_ts)}")

    print(f"[DC오프셋 제거] 윈도우={DC_WINDOW}")
    data_clean = remove_dc_offset(data, DC_WINDOW)

    sample_ts = expand_timestamps(bank_ts)

    meta = None
    if is_first_part(in_path) and args.meta:
        meta = load_metadata(args.meta)
        if meta is None:
            print(f"[경고] 메타데이터 파일을 못 찾음: {args.meta} - 헤더 없이 진행")

    print(f"[CSV 저장] {out_path} (start_idx={args.start_idx})")
    write_csv(out_path, sample_ts, data_clean, meta, start_idx=args.start_idx)
    print(f"[완료] 다음 파일 start_idx={args.start_idx + data.shape[0]}")


if __name__ == "__main__":
    main()
