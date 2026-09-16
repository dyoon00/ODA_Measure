"""
전력 CSV(part001.csv)에서 16384개짜리 무작위 연속 구간을 뽑아 FFT를 계산하고,
채널별 FFT 그래프 9장을 생성 (단일 채널 7장 + 전압/전류 조합 2장).

사용법:
  python3 generate_power_fft.py <입력.csv> <출력폴더>
"""
import os
import sys
import random
import argparse

import matplotlib
import numpy as np

from plot_waveform import load_csv, _skip_metadata_header
from generate_power_graphs import count_data_rows

FFT_WINDOW = 16384
SAMPLE_RATE_HZ = 16000  # 62.5us 주기 (실측 확인됨)

CHANNELS = ["V_R", "V_S", "V_T", "I_R", "I_S", "I_T", "I_N"]
UNITS = {"V_R": "V", "V_S": "V", "V_T": "V", "I_R": "A", "I_S": "A", "I_T": "A", "I_N": "A"}
COLORS = {
    "V_R": "red", "V_S": "green", "V_T": "blue",
    "I_R": "red", "I_S": "green", "I_T": "blue", "I_N": "gray",
}


def compute_fft(values, sample_rate=SAMPLE_RATE_HZ):
    """실수 FFT -> (주파수축[Hz], 진폭 스펙트럼) 반환. DC성분(0Hz)은 제외."""
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    window = np.hanning(n)  # 스펙트럼 누설(leakage) 완화
    spectrum = np.fft.rfft(arr * window)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    magnitude = np.abs(spectrum) * 2.0 / np.sum(window)  # 윈도우 보정
    return freqs[1:], magnitude[1:]  # 0Hz(DC) 제외


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("outdir")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-freq", type=float, default=2000.0,
                         help="그래프에 표시할 최대 주파수 (Hz), 기본 2000Hz(60Hz의 약 33차 고조파까지)")
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

    data = load_csv(args.csv_path, start=start, count=FFT_WINDOW)

    fft_result = {}
    for ch in CHANNELS:
        freqs, mag = compute_fft(data[ch])
        fft_result[ch] = (freqs, mag)
        peak_idx = np.argmax(mag)
        print(f"  {ch}: 최대 피크 = {freqs[peak_idx]:.1f}Hz ({mag[peak_idx]:.4f}{UNITS[ch]})")

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    freq_mask = fft_result[CHANNELS[0]][0] <= args.max_freq

    # 1) 단일 채널 FFT 7장
    for ch in CHANNELS:
        freqs, mag = fft_result[ch]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(freqs[freq_mask], mag[freq_mask], color=COLORS[ch], linewidth=0.9)
        ax.set_title(f"{ch} FFT")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel(f"Amplitude ({UNITS[ch]})")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        out_path = os.path.join(args.outdir, f"{ch}_fft.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"[저장됨] {out_path}")

    # 2) 전압 조합 FFT
    fig, ax = plt.subplots(figsize=(12, 5))
    for ch in ("V_R", "V_S", "V_T"):
        freqs, mag = fft_result[ch]
        ax.plot(freqs[freq_mask], mag[freq_mask], color=COLORS[ch], linewidth=0.8, label=ch)
    ax.set_title("Voltage FFT (R/S/T)")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Amplitude (V)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = os.path.join(args.outdir, "voltage_RST_fft.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[저장됨] {out_path}")

    # 3) 전류 조합 FFT
    fig, ax = plt.subplots(figsize=(12, 5))
    for ch in ("I_R", "I_S", "I_T", "I_N"):
        freqs, mag = fft_result[ch]
        style = "--" if ch == "I_N" else "-"
        ax.plot(freqs[freq_mask], mag[freq_mask], color=COLORS[ch], linewidth=0.8,
                linestyle=style, label=ch)
    ax.set_title("Current FFT (R/S/T/N)")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Amplitude (A)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = os.path.join(args.outdir, "current_RSTN_fft.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[저장됨] {out_path}")

    print("[완료] FFT 그래프 9장 생성됨")


if __name__ == "__main__":
    main()
