"""
전력 CSV(part001.csv)에서 16384개짜리 무작위 연속 구간을 뽑아
채널별 RMS를 계산하고, 그 중 앞 1200개(약 4주기)로 파형 그래프 9장을 생성.

  - 단일 채널 그래프 7장: V_R, V_S, V_T, I_R, I_S, I_T, I_N
  - 조합 그래프 2장: 전압(V_R+V_S+V_T), 전류(I_R+I_S+I_T+I_N)

사용법:
  python3 generate_power_graphs.py <입력.csv> <출력폴더>
"""
import os
import sys
import random
import argparse

import matplotlib
import numpy as np

from plot_waveform import load_csv, _skip_metadata_header

RMS_WINDOW = 16384
PLOT_SAMPLES = 1200

CHANNELS = ["V_R", "V_S", "V_T", "I_R", "I_S", "I_T", "I_N"]
UNITS = {"V_R": "V", "V_S": "V", "V_T": "V", "I_R": "A", "I_S": "A", "I_T": "A", "I_N": "A"}
COLORS = {
    "V_R": "red", "V_S": "green", "V_T": "blue",
    "I_R": "red", "I_S": "green", "I_T": "blue", "I_N": "gray",
}


def count_data_rows(path):
    """메타데이터 헤더/컬럼헤더를 건너뛰고 실제 데이터 행 수만 셈"""
    with open(path, "r", encoding="utf-8") as f:
        _skip_metadata_header(f)
        return sum(1 for _ in f)


def compute_rms(values):
    arr = np.asarray(values, dtype=np.float64)
    return float(np.sqrt(np.mean(arr ** 2)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("outdir")
    parser.add_argument("--seed", type=int, default=None, help="테스트 재현용 (기본은 매번 무작위)")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    os.makedirs(args.outdir, exist_ok=True)

    total_rows = count_data_rows(args.csv_path)
    print(f"[정보] 전체 데이터 행 수 = {total_rows}")

    if total_rows < RMS_WINDOW:
        print(f"[에러] 데이터가 {RMS_WINDOW}개보다 적어서 진행할 수 없습니다.")
        sys.exit(1)

    start = random.randint(0, total_rows - RMS_WINDOW)
    print(f"[정보] 무작위 구간 선택: start={start}, 길이={RMS_WINDOW}")

    data = load_csv(args.csv_path, start=start, count=RMS_WINDOW)

    # RMS는 16384개 전체로, 그래프는 그 중 앞 1200개만
    rms = {ch: compute_rms(data[ch]) for ch in CHANNELS}
    for ch in CHANNELS:
        print(f"  RMS[{ch}] = {rms[ch]:.4f}{UNITS[ch]}")

    plot_idx = data["idx"][:PLOT_SAMPLES]
    plot_data = {ch: data[ch][:PLOT_SAMPLES] for ch in CHANNELS}

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 1) 단일 채널 그래프 7장
    for ch in CHANNELS:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(plot_idx, plot_data[ch], color=COLORS[ch], linewidth=0.9)
        ax.set_title(f"{ch}  (RMS = {rms[ch]:.3f}{UNITS[ch]})")
        ax.set_xlabel("Sample index")
        ax.set_ylabel(f"{ch} ({UNITS[ch]})")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        out_path = os.path.join(args.outdir, f"{ch}.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"[저장됨] {out_path}")

    # 2) 전압 조합 그래프 (V_R, V_S, V_T)
    fig, ax = plt.subplots(figsize=(12, 5))
    for ch in ("V_R", "V_S", "V_T"):
        ax.plot(plot_idx, plot_data[ch], color=COLORS[ch], linewidth=0.8,
                label=f"{ch} (RMS={rms[ch]:.2f}V)")
    ax.set_title("Voltage (R/S/T)")
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Voltage (V)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = os.path.join(args.outdir, "voltage_RST.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[저장됨] {out_path}")

    # 3) 전류 조합 그래프 (I_R, I_S, I_T, I_N)
    fig, ax = plt.subplots(figsize=(12, 5))
    for ch in ("I_R", "I_S", "I_T", "I_N"):
        style = "--" if ch == "I_N" else "-"
        ax.plot(plot_idx, plot_data[ch], color=COLORS[ch], linewidth=0.8, linestyle=style,
                label=f"{ch} (RMS={rms[ch]:.3f}A)")
    ax.set_title("Current (R/S/T/N)")
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Current (A)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = os.path.join(args.outdir, "current_RSTN.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[저장됨] {out_path}")

    print("[완료] 그래프 9장 생성됨")


if __name__ == "__main__":
    main()
