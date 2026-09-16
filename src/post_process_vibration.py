"""
collect_vibration.py로 저장한 x/y/z 3개 .bin 파일(같은 part 세트)을 읽어서
하나의 tab-separated CSV(idx, timestamp, x, y, z)로 합침.
part001 세트에는 메타데이터 헤더 포함.

사용법:
  python3 post_process_vibration.py <입력_x.bin> [출력.csv] [--meta metadata.json]

  (x.bin 경로만 주면 같은 폴더의 _y.bin, _z.bin을 자동으로 찾음)
"""
import sys
import struct
import argparse
import datetime
import numpy as np

from metadata_utils import load_metadata, write_metadata_header, is_first_part

FFT_LEN = 16384
SLOT_RECORD_HEADER = 8  # 타임스탬프(double)
SLOT_DATA_BYTES = FFT_LEN * 4  # float32
SLOT_RECORD_BYTES = SLOT_RECORD_HEADER + SLOT_DATA_BYTES


def read_bin_file(path):
    """슬롯 레코드들을 읽어서 (timestamps[nslots], data[N]) 반환 (한 축)"""
    timestamps = []
    chunks = []

    with open(path, "rb") as f:
        while True:
            header = f.read(SLOT_RECORD_HEADER)
            if len(header) < SLOT_RECORD_HEADER:
                break
            (ts,) = struct.unpack("<d", header)

            body = f.read(SLOT_DATA_BYTES)
            if len(body) < SLOT_DATA_BYTES:
                print(f"[경고] {path}: 마지막 슬롯이 불완전함(파일이 도중에 잘림) - 버림")
                break

            arr = np.frombuffer(body, dtype="<f4")
            timestamps.append(ts)
            chunks.append(arr)

    if not chunks:
        return np.array([]), np.zeros((0,), dtype=np.float32)

    data = np.concatenate(chunks, axis=0)
    return np.array(timestamps), data


def expand_timestamps(slot_timestamps):
    return np.repeat(slot_timestamps, FFT_LEN)


def format_timestamp(unix_ts):
    return datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S.%f")


def x_path_to_yz(x_path):
    if "_x.bin" not in x_path:
        raise ValueError(f"x.bin 파일 경로가 아님: {x_path}")
    return x_path.replace("_x.bin", "_y.bin"), x_path.replace("_x.bin", "_z.bin")


def write_csv(path, timestamps, x, y, z, meta, start_idx=0):
    with open(path, "w", encoding="utf-8") as f:
        if meta is not None:
            write_metadata_header(f, meta)
        f.write("idx\ttimestamp\tx\ty\tz\n")
        n = len(x)
        for i in range(n):
            f.write(
                f"{start_idx + i}\t{format_timestamp(timestamps[i])}\t"
                f"{x[i]:.8f}\t{y[i]:.8f}\t{z[i]:.8f}\n"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("x_bin_path", help="x축 .bin 경로 (y/z는 자동으로 찾음)")
    parser.add_argument("csv_path", nargs="?", default=None)
    parser.add_argument("--meta", default=None, help="metadata.json 경로 (part001일 때만 헤더에 씀)")
    parser.add_argument("--start-idx", type=int, default=0, help="이 파일의 idx 시작값 (여러 part를 이어붙일 때 사용)")
    args = parser.parse_args()

    x_path = args.x_bin_path
    y_path, z_path = x_path_to_yz(x_path)
    out_path = args.csv_path if args.csv_path else x_path.replace("_x.bin", ".csv")

    print(f"[읽는 중] {x_path}, {y_path}, {z_path}")
    ts_x, data_x = read_bin_file(x_path)
    ts_y, data_y = read_bin_file(y_path)
    ts_z, data_z = read_bin_file(z_path)

    n = min(len(data_x), len(data_y), len(data_z))
    if n == 0:
        print("[에러] 데이터가 없습니다.")
        sys.exit(1)
    if len(data_x) != len(data_y) or len(data_y) != len(data_z):
        print(f"[경고] x/y/z 샘플수가 다름 (x={len(data_x)}, y={len(data_y)}, z={len(data_z)}) - 짧은 쪽 기준으로 자름")

    print(f"[정보] 총 샘플수={n}")

    sample_ts = expand_timestamps(ts_x)[:n]

    meta = None
    if is_first_part(x_path) and args.meta:
        meta = load_metadata(args.meta)
        if meta is None:
            print(f"[경고] 메타데이터 파일을 못 찾음: {args.meta} - 헤더 없이 진행")

    print(f"[CSV 저장] {out_path} (start_idx={args.start_idx})")
    write_csv(out_path, sample_ts, data_x[:n], data_y[:n], data_z[:n], meta, start_idx=args.start_idx)
    print(f"[완료] 다음 파일 start_idx={args.start_idx + n}")


if __name__ == "__main__":
    main()
