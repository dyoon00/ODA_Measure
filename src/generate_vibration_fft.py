"""
진동 CSV(part001.csv, idx/timestamp/x/y/z)에서 16384개짜리 무작위 연속 구간을 뽑아
x/y/z 축별 FFT 그래프 4장을 생성 (단일 축 3장 + x/y/z 조합 1장).

사용법:
  python3 generate_vibration_fft.py <입력.csv> <출력폴더>
"""
import os
import sys
import csv
import random
import argparse

import matplotlib
import numpy as np

from plot_waveform import _skip_metadata_header

FFT_WINDOW = 16384
SAMPLE_RATE_HZ = 26667  # IIS3DWB 실측 샘플레이트

AXES = ["x", "y", "z"]
COLORS = {"x": "red", "y": "green", "z": "blue"}


def count_data_rows(path):
    with open(path, "r", encoding="utf-8") as f:
        _skip_metadata_header(f)
        return sum(1 for _ in f)


def load_vibration_csv(path, start, count):
    idx_list, x, y, z = [], [], [], []
    with open(path, "r", encoding="utf-8") as f:
        header_line = _skip_metadata_header(f)
        fieldnames = header_line.strip().split("\t")
        reader = csv.DictReader(f, fieldnames=fieldnames, delimiter="\t")
        for row_num, row in enumerate(reader):
            if row_num < start:
                continue
            if row_num >= start + count:
                break
            idx_list.append(int(row["idx"]))
            x.append(float(row["x"]))
            y.append(float(row["y"]))
            z.append(float(row["z"]))
    return {"idx": idx_list, "x": x, "y": y, "z": z}


def compute_fft(values, sample_rate=SAMPLE_RATE_HZ):
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    window = np.hanning(n)
    spectrum = np.fft.rfft(arr * window)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    magnitude = np.abs(spectrum) * 2.0 / np.sum(window)
    return freqs[1:], magnitude[1:]  # 0Hz(DC) 제외


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("outdir")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-freq", type=float, default=13333.0,
                         help="그래프에 표시할 최대 주파수 (Hz), 기본은 나이퀴스트(26667/2)")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    os.makedirs(args.outdir, exist_ok=True)

    total_rows = count_data_rows(args.csv_path)
    print(f"[정보] 전체 데이터 행 수 = {total_rows}")

    if total_rows < FFT_WINDOW:
        print(f"[에러] 데이터가 {FFT_WINDOW}개보다 적어서 진행할 수 없습니다.")
        sys.exit(1)

    start = random.randint(0, total_rows - FFT_WINDOW)
    print(f"[정보] 무작위 구간 선택: start={start}, 길이={FFT_WINDOW}")

    data = load_vibration_csv(args.csv_path, start=start, count=FFT_WINDOW)

    fft_result = {}
    for ax_name in AXES:
        freqs, mag = compute_fft(data[ax_name])
        fft_result[ax_name] = (freqs, mag)
        peak_idx = np.argmax(mag)
        print(f"  {ax_name}: 최대 피크 = {freqs[peak_idx]:.1f}Hz ({mag[peak_idx]:.5f}g)")

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    freq_mask = fft_result["x"][0] <= args.max_freq

    # 1) 단일 축 FFT 3장
    for ax_name in AXES:
        freqs, mag = fft_result[ax_name]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(freqs[freq_mask], mag[freq_mask], color=COLORS[ax_name], linewidth=0.8)
        ax.set_title(f"{ax_name.upper()}-axis FFT")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Amplitude (g)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        out_path = os.path.join(args.outdir, f"{ax_name}_fft.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"[저장됨] {out_path}")

    # 2) x/y/z 조합 FFT 1장
    fig, ax = plt.subplots(figsize=(12, 5))
    for ax_name in AXES:
        freqs, mag = fft_result[ax_name]
        ax.plot(freqs[freq_mask], mag[freq_mask], color=COLORS[ax_name], linewidth=0.8,
                label=ax_name.upper())
    ax.set_title("Vibration FFT (X/Y/Z)")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Amplitude (g)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = os.path.join(args.outdir, "xyz_fft.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[저장됨] {out_path}")

    print("[완료] 진동 FFT 그래프 4장 생성됨")


if __name__ == "__main__":
    main()
