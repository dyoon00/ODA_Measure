"""
post_process.py로 만든 CSV(전압/전류 순시값)를 그래프로 그림.

사용법:
  python3 plot_waveform.py <입력.csv> [--start N] [--count N] [--save 출력.png]

옵션:
  --start N   : 몇 번째 샘플부터 그릴지 (기본 0)
  --count N   : 몇 개 샘플을 그릴지 (기본 2000, 너무 많으면 그래프가 무거워짐)
  --save PATH : 화면에 띄우지 않고 파일로 저장 (라즈베리파이에 디스플레이 없을 때 유용)
"""
import sys
import argparse
import csv

import matplotlib
import matplotlib.pyplot as plt


def _skip_metadata_header(f):
    """260913: part001.csv는 앞에 key\\tvalue 메타데이터 14줄 + 빈 줄이 있을 수 있음.
    첫 줄이 'idx'로 시작하는 컬럼헤더가 아니면, 빈 줄이 나올 때까지 건너뜀."""
    first_line = f.readline()
    if first_line.startswith("idx\t"):
        return first_line  # 메타데이터 없음, 이 줄이 바로 컬럼헤더
    # 메타데이터 있음 - 빈 줄까지 건너뛰고 그 다음 줄(컬럼헤더)을 반환
    line = first_line
    while line.strip() != "":
        line = f.readline()
    return f.readline()


def load_csv(path, start, count):
    idx_list = []
    v_r, v_s, v_t = [], [], []
    i_r, i_s, i_t, i_n = [], [], [], []

    with open(path, "r", encoding="utf-8") as f:
        header_line = _skip_metadata_header(f)
        fieldnames = header_line.strip().split("\t")
        reader = csv.DictReader(f, fieldnames=fieldnames, delimiter="\t")
        for row_num, row in enumerate(reader):
            if row_num < start:
                continue
            if count is not None and row_num >= start + count:
                break

            idx_list.append(int(row["idx"]))
            v_r.append(float(row["V_R"]))
            v_s.append(float(row["V_S"]))
            v_t.append(float(row["V_T"]))
            i_r.append(float(row["I_R"]))
            i_s.append(float(row["I_S"]))
            i_t.append(float(row["I_T"]))
            i_n.append(float(row["I_N"]))

    return {
        "idx": idx_list,
        "V_R": v_r, "V_S": v_s, "V_T": v_t,
        "I_R": i_r, "I_S": i_s, "I_T": i_t, "I_N": i_n,
    }


def plot(data, title, save_path=None):
    if save_path:
        matplotlib.use("Agg")  # 화면 없이 파일로만 저장

    fig, (ax_v, ax_i) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    idx = data["idx"]

    ax_v.plot(idx, data["V_R"], label="V_R", color="red", linewidth=0.8)
    ax_v.plot(idx, data["V_S"], label="V_S", color="green", linewidth=0.8)
    ax_v.plot(idx, data["V_T"], label="V_T", color="blue", linewidth=0.8)
    ax_v.set_ylabel("Voltage (V)")
    ax_v.legend(loc="upper right")
    ax_v.grid(True, alpha=0.3)
    ax_v.set_title(f"{title} - Voltage")

    ax_i.plot(idx, data["I_R"], label="I_R", color="red", linewidth=0.8)
    ax_i.plot(idx, data["I_S"], label="I_S", color="green", linewidth=0.8)
    ax_i.plot(idx, data["I_T"], label="I_T", color="blue", linewidth=0.8)
    ax_i.plot(idx, data["I_N"], label="I_N", color="gray", linewidth=0.8, linestyle="--")
    ax_i.set_ylabel("Current (A)")
    ax_i.set_xlabel("Sample index")
    ax_i.legend(loc="upper right")
    ax_i.grid(True, alpha=0.3)
    ax_i.set_title(f"{title} - Current")

    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"[저장됨] {save_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--save", type=str, default=None)
    args = parser.parse_args()

    print(f"[읽는 중] {args.csv_path} (start={args.start}, count={args.count})")
    data = load_csv(args.csv_path, args.start, args.count)

    if len(data["idx"]) == 0:
        print("[에러] 읽은 데이터가 없습니다. --start 값이 파일 범위를 벗어났을 수 있습니다.")
        sys.exit(1)

    print(f"[정보] {len(data['idx'])}개 샘플 로드됨")

    plot(data, title=args.csv_path, save_path=args.save)


if __name__ == "__main__":
    main()
