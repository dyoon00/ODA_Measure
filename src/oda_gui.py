"""
전력+진동 동시 수집 GUI (tkinter, 최소 부하 지향)

- GUI 자체는 아무 코어에도 고정하지 않고, 무거운 작업(그래프/계산)은 전혀 하지 않음
- [시작] 누르면: result/<파일명>/에 폴더 생성 + metadata.json 저장 +
  전력/진동 각각 OpenOCD+수집 파이썬을 taskset(진동은 chrt까지)으로 감싸서 subprocess 실행
- [종료] 누르면: 4개 프로세스 정리 + post_process_power.py / post_process_vibration.py로 후처리
- 상태 표시는 1초에 한 번, .bin 폴더의 파일 개수만 가볍게 확인 (로그 스트림은 안 받음)

사전 조건 (직접 확인 필요):
  - ST-LINK 시리얼 번호 2개(POWER_SERIAL, VIB_SERIAL)가 실제 장치와 일치해야 함
  - sudo chrt를 비밀번호 없이 쓰려면 sudoers에 등록 필요 (아니면 시작시 터미널에서 sudo 암호 캐시)
"""
import os
import sys
import json
import glob
import time
import signal
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from metadata_utils import META_FIELDS  # 260914: 필드 목록 중복 관리 방지 - 여기서만 정의

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_ROOT = os.path.expanduser("~/Desktop/ODA_Measure/result")
LOGO_PATH = os.path.join(BASE_DIR, "..", "odalogo_horizon.png")  # ODA_Measure 폴더 바로 밑

POWER_SERIAL = "002500433234511337333934"
VIB_SERIAL = "002600483335510B35383531"  # 260914: ST-LINK 교체됨

POWER_TCL_PORT = 6668
VIB_TCL_PORT = 6666

POLL_MS = 30000  # 260913: 파일누적량+오버런 확인을 하나로 합쳐서 30초에 한 번만 (부하 최소화)

# 파일 내용을 열어보지 않고, 파일 크기(바이트)만으로 샘플수를 역산하기 위한 레코드 크기
POWER_RECORD_BYTES = 8 + 256 * 7 * 4   # 타임스탬프(8B) + 256프레임x7채널 float32 = 7176
POWER_SAMPLES_PER_RECORD = 256
VIB_RECORD_BYTES = 8 + 16384 * 4       # 타임스탬프(8B) + 16384개 float32 = 65544
VIB_SAMPLES_PER_RECORD = 16384


def dir_total_bytes(dir_path, pattern="*.bin"):
    """파일을 열지 않고 크기(stat)만 합산 - glob+열기보다 훨씬 가벼움"""
    total = 0
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(pattern.lstrip("*")):
                    total += entry.stat().st_size
    except FileNotFoundError:
        pass
    return total


def read_status_file(path):
    """260913: GUI가 OpenOCD에 직접 접속하지 않고, 수집 스크립트가 이미 써둔
    상태파일(power_status.json / vibration_status.json)만 읽음 - 자원경합 원천 차단"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def power_openocd_cmd(port_override=None):
    port = port_override or POWER_TCL_PORT
    return [
        "taskset", "-c", "1", "openocd",
        "-f", "interface/stlink.cfg", "-f", "target/stm32u5x.cfg",
        "-c", f"adapter serial {POWER_SERIAL}",
        "-c", "adapter speed 24000",
        "-c", f"tcl port {port}",
        "-c", "telnet port 4444",
        "-c", "gdb port 3333",
    ]


def vib_openocd_cmd(port_override=None):
    port = port_override or VIB_TCL_PORT
    return [
        "sudo", "chrt", "-f", "50", "taskset", "-c", "2", "openocd",
        "-f", "interface/stlink.cfg", "-f", "target/stm32u5x.cfg",
        "-c", f"adapter serial {VIB_SERIAL}",
        "-c", "adapter speed 24000",
        "-c", f"tcl port {port}",
        "-c", "telnet port 4445",
        "-c", "gdb port 3334",
    ]


# 260913: ODA Technologies 브랜드 컬러(#eb4c00) 기반 팔레트
ACCENT = "#eb4c00"        # 브랜드 컬러 (메인 오렌지)
ACCENT_DARK = "#b83900"   # 브랜드 컬러보다 진한 톤 (종료 버튼, hover)
ACCENT_LIGHT = "#ffddc9"  # 브랜드 컬러의 밝은 틴트 (테두리, 은은한 강조)
ACCENT_SOFT = "#fff0e6"   # 아주 옅은 틴트 (카드 안 강조 영역 등)
BG = "#fbf6f2"            # 따뜻한 중성 배경 (브랜드 컬러와 어울리는 아이보리)
CARD_BG = "#ffffff"       # 카드 배경 - 흰색으로 브랜드 컬러 대비를 또렷하게
RED = "#c0392b"           # 경고(유실 발생) 전용 - 브랜드 오렌지와 확실히 구분되는 진홍색
TEXT_MAIN = "#2b1d14"     # 진한 웜톤 다크 (가독성 좋은 메인 텍스트)
TEXT_SUB = "#8a6a58"      # 브라운 계열 보조 텍스트


class App:
    def __init__(self, root):
        self.root = root
        root.title("전력+진동 동시 수집")
        root.configure(bg=BG)

        # 260914: 화면 높이를 넘는 창이 뜨지 않도록, 화면 크기 기준으로 초기 창 크기를 잡음
        # (내용이 더 길면 캔버스 스크롤로 보게 됨)
        screen_h = root.winfo_screenheight()
        screen_w = root.winfo_screenwidth()
        win_h = min(760, int(screen_h * 0.9))
        win_w = min(620, int(screen_w * 0.9))
        root.geometry(f"{win_w}x{win_h}")

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TLabelframe", background=CARD_BG, bordercolor=ACCENT_LIGHT, borderwidth=2)
        style.configure("TLabelframe.Label", background=CARD_BG, foreground=ACCENT_DARK,
                         font=("NanumGothic", 11, "bold"))
        style.configure("TLabel", background=CARD_BG, foreground=TEXT_MAIN, font=("NanumGothic", 10))

        # 상태 카드는 살짝 다른(옅은 브랜드 틴트) 배경으로 시각적으로 구분
        style.configure("Status.TLabelframe", background=ACCENT_SOFT, bordercolor=ACCENT_LIGHT, borderwidth=2)
        style.configure("Status.TLabelframe.Label", background=ACCENT_SOFT, foreground=ACCENT_DARK,
                         font=("NanumGothic", 11, "bold"))
        style.configure("Status.TLabel", background=ACCENT_SOFT, foreground=TEXT_MAIN, font=("NanumGothic", 10))
        style.configure("Title.TLabel", background=BG, foreground=ACCENT_DARK, font=("NanumGothic", 18, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=TEXT_SUB, font=("NanumGothic", 10))
        style.configure("TEntry", padding=5, fieldbackground="#ffffff", bordercolor=ACCENT_LIGHT)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT_MAIN, font=("NanumGothic", 10))

        style.configure("Start.TButton", background=ACCENT, foreground="white",
                         font=("NanumGothic", 12, "bold"), padding=10, borderwidth=0)
        style.map("Start.TButton", background=[("disabled", ACCENT_LIGHT), ("active", ACCENT_DARK)])
        style.configure("Stop.TButton", background=ACCENT_DARK, foreground="white",
                         font=("NanumGothic", 12, "bold"), padding=10, borderwidth=0)
        style.map("Stop.TButton", background=[("disabled", "#e8c8a8"), ("active", "#9c4c09")])

        # 260914: 화면(특히 라즈베리파이 작은 해상도)보다 내용이 길어서 아래쪽(버튼 등)이
        # 잘려 안 보이는 문제 -> 전체를 스크롤 가능한 캔버스 안에 넣음
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        outer = ttk.Frame(canvas, padding=18, style="TFrame")
        outer_window = canvas.create_window((0, 0), window=outer, anchor="nw")

        def _on_outer_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        outer.bind("<Configure>", _on_outer_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(outer_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            delta = event.delta if event.delta else (120 if getattr(event, "num", 0) == 4 else -120)
            canvas.yview_scroll(int(-delta / 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)      # Windows/일부 X11
        canvas.bind_all("<Button-4>", _on_mousewheel)        # Linux 휠 위
        canvas.bind_all("<Button-5>", _on_mousewheel)        # Linux 휠 아래

        title_box = ttk.Frame(outer, style="TFrame")
        title_box.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        # 260913: ODA Technologies 로고 (있으면 표시, 없거나 로드 실패해도 조용히 텍스트만 표시)
        self._logo_img = self._load_logo(max_height=44)
        if self._logo_img is not None:
            tk.Label(title_box, image=self._logo_img, bg=BG).pack(anchor="w", pady=(0, 6))

        ttk.Label(title_box, text="⚡ 전력 + 진동 동시 수집", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="ODA Measure", style="Subtitle.TLabel").pack(anchor="w")

        divider = tk.Frame(outer, bg=ACCENT, height=3)
        divider.grid(row=1, column=0, sticky="ew", pady=(6, 14))

        meta_card = ttk.LabelFrame(outer, text="측정 정보", padding=14)
        meta_card.grid(row=2, column=0, sticky="ew")

        self.entries = {}
        for i, field in enumerate(META_FIELDS):
            ttk.Label(meta_card, text=field).grid(row=i, column=0, sticky="e", padx=(0, 8), pady=3)
            e = ttk.Entry(meta_card, width=30)
            e.grid(row=i, column=1, pady=3)
            self.entries[field] = e

        self.entries["날짜"].insert(0, time.strftime("%Y-%m-%d"))

        self.make_graph_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            meta_card, text="시계열 그래프 만들기 (전압/전류, 종료 후 자동 생성)",
            variable=self.make_graph_var
        ).grid(row=len(META_FIELDS), column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.make_power_fft_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            meta_card, text="전압/전류 FFT 그래프 만들기",
            variable=self.make_power_fft_var
        ).grid(row=len(META_FIELDS) + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.make_vib_fft_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            meta_card, text="진동 FFT 그래프 만들기",
            variable=self.make_vib_fft_var
        ).grid(row=len(META_FIELDS) + 2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        btn_frame = ttk.Frame(outer, style="TFrame")
        btn_frame.grid(row=3, column=0, sticky="ew", pady=14)
        self.start_btn = ttk.Button(btn_frame, text="▶  시작", command=self.on_start, style="Start.TButton")
        self.start_btn.pack(side="left", padx=(0, 8), fill="x", expand=True)
        self.stop_btn = ttk.Button(btn_frame, text="■  종료", command=self.on_stop,
                                    state="disabled", style="Stop.TButton")
        self.stop_btn.pack(side="left", fill="x", expand=True)

        status_card = ttk.LabelFrame(outer, text="상태", padding=14)
        status_card.grid(row=4, column=0, sticky="ew")
        status_card.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(status_card, textvariable=self.status_var,
                  font=("NanumGothic", 10)).grid(row=0, column=0, sticky="w", pady=2)

        # 260913: 유실 발생시 빨간색으로 강조해야 해서, 색을 직접 제어 가능한 tk.Label 사용
        self.counter_label = tk.Label(
            status_card, text="", bg=CARD_BG, fg=TEXT_SUB,
            font=("NanumGothic", 10, "bold"), anchor="w", justify="left",
        )
        self.counter_label.grid(row=1, column=0, sticky="w", pady=(6, 2))

        self.progress_var = tk.StringVar(value="")
        ttk.Label(status_card, textvariable=self.progress_var,
                  foreground=TEXT_SUB).grid(row=2, column=0, sticky="w", pady=(6, 2))

        self.procs = {}  # name -> Popen
        self.result_dir = None
        self.poll_job = None

    def _load_logo(self, max_height=44):
        """ODA_Measure/odalogo_horizon.png를 읽어서 높이 기준으로 축소한 PhotoImage 반환.
        파일이 없거나 Pillow가 없으면 조용히 None (로고 없이 텍스트만 표시)."""
        if not os.path.exists(LOGO_PATH):
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(LOGO_PATH)
            ratio = max_height / img.height
            img = img.resize((int(img.width * ratio), max_height), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except ImportError:
            # Pillow가 없으면 tkinter 기본 PhotoImage로 시도 (배율 축소만 가능, 화질은 떨어짐)
            try:
                img = tk.PhotoImage(file=LOGO_PATH)
                factor = max(1, img.height() // max_height)
                return img.subsample(factor, factor)
            except Exception:
                return None
        except Exception:
            return None

    def _get_meta(self):
        return {field: self.entries[field].get() for field in META_FIELDS}

    def on_start(self):
        meta = self._get_meta()
        name = meta["파일명"].strip()
        if not name:
            messagebox.showerror("에러", "파일명(측정명)을 입력해주세요.")
            return

        self.result_dir = os.path.join(RESULT_ROOT, name)
        power_bin = os.path.join(self.result_dir, "power_bin")
        vib_bin = os.path.join(self.result_dir, "vibration_bin")
        os.makedirs(power_bin, exist_ok=True)
        os.makedirs(vib_bin, exist_ok=True)

        meta_path = os.path.join(self.result_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        self.meta_path = meta_path

        try:
            self.procs["power_openocd"] = subprocess.Popen(
                power_openocd_cmd(), cwd=BASE_DIR,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.procs["vib_openocd"] = subprocess.Popen(
                vib_openocd_cmd(), cwd=BASE_DIR,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(2)  # OpenOCD가 타겟 연결(examine)까지 끝날 시간을 줌

            self.procs["power_py"] = subprocess.Popen(
                ["taskset", "-c", "1", "python3", "collect_power.py", "--outdir", power_bin],
                cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.procs["vib_py"] = subprocess.Popen(
                ["sudo", "chrt", "-f", "50", "taskset", "-c", "2", "python3",
                 "collect_vibration.py", "--outdir", vib_bin],
                cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            messagebox.showerror("실행 에러", str(e))
            return

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set(f"수집 중... ({name})")
        self.progress_var.set("")
        self.counter_label.config(text="오버런/누락 확인 중... (수집 스크립트의 첫 상태파일 기록 대기)", fg=TEXT_SUB)

        self._schedule_poll()

    def _schedule_poll(self):
        self.poll_job = self.root.after(POLL_MS, self._poll_all)

    def _poll_all(self):
        """260913: 파일누적량 + 오버런/missed_drdy를 30초에 한 번, 한 타이머로 같이 확인 (부하 최소화)"""
        if self.result_dir is None:
            return

        power_bin = os.path.join(self.result_dir, "power_bin")
        vib_bin = os.path.join(self.result_dir, "vibration_bin")

        power_bytes = dir_total_bytes(power_bin, "*.bin")
        vib_bytes = dir_total_bytes(vib_bin, "_x.bin")  # x만 세서 3중 카운트 방지
        n_power_samples = (power_bytes // POWER_RECORD_BYTES) * POWER_SAMPLES_PER_RECORD
        n_vib_samples = (vib_bytes // VIB_RECORD_BYTES) * VIB_SAMPLES_PER_RECORD

        self.status_var.set(
            f"수집 중... 전력={n_power_samples:,}샘플 진동={n_vib_samples:,}샘플"
        )

        # 260913: OpenOCD에 직접 접속하지 않고, 수집 스크립트가 이미 써둔 상태파일만 읽음
        power_status = read_status_file(os.path.join(power_bin, "power_status.json"))
        vib_status = read_status_file(os.path.join(vib_bin, "vibration_status.json"))

        d_overflow = power_status.get("overflow_session", "확인불가") if power_status else "확인불가"
        d_missed = power_status.get("missed_drdy_session", "확인불가") if power_status else "확인불가"
        d_overrun = vib_status.get("overrun_session", "확인불가") if vib_status else "확인불가"

        loss_detected = any(d not in ("확인불가", 0, None) for d in (d_overflow, d_missed, d_overrun))
        warn = " ⚠ 유실 발생!" if loss_detected else ""

        self.counter_label.config(
            text=f"[이번 세션 유실] 전력 overflow={d_overflow} missed_drdy={d_missed} | 진동 overrun={d_overrun}{warn}",
            fg=RED if loss_detected else TEXT_SUB,
        )
        self._schedule_poll()

    def on_stop(self):
        if self.poll_job:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None

        self.status_var.set("종료 중...")
        self.root.update()

        # 파이썬 수집 스크립트 먼저 정상 종료(SIGINT, KeyboardInterrupt로 파일 flush 유도)
        for name in ("power_py", "vib_py"):
            p = self.procs.get(name)
            if p and p.poll() is None:
                try:
                    p.send_signal(signal.SIGINT)
                except Exception:
                    pass
        time.sleep(2)
        for name in ("power_py", "vib_py"):
            p = self.procs.get(name)
            if p and p.poll() is None:
                p.terminate()

        # OpenOCD 종료
        for name in ("power_openocd", "vib_openocd"):
            p = self.procs.get(name)
            if p and p.poll() is None:
                p.terminate()

        time.sleep(1)
        self.status_var.set("후처리(CSV 변환) 중...")
        self.root.update()
        self._run_post_process()

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("완료")

    def _run_post_process(self):
        power_bin = os.path.join(self.result_dir, "power_bin")
        power_csv = os.path.join(self.result_dir, "power_csv")
        vib_bin = os.path.join(self.result_dir, "vibration_bin")
        vib_csv = os.path.join(self.result_dir, "vibration_csv")
        os.makedirs(power_csv, exist_ok=True)
        os.makedirs(vib_csv, exist_ok=True)

        power_files = sorted(glob.glob(os.path.join(power_bin, "*.bin")))
        vib_files = sorted(glob.glob(os.path.join(vib_bin, "*_x.bin")))
        total = len(power_files) + len(vib_files)
        done = 0

        def report():
            pct = int(done / total * 100) if total else 100
            self.progress_var.set(f"CSV 변환 중... {done}/{total} ({pct}%)")
            self.root.update()

        report()
        power_start_idx = 0
        for bin_path in power_files:
            out_path = os.path.join(power_csv, os.path.basename(bin_path).replace(".bin", ".csv"))
            subprocess.run(
                ["python3", "post_process_power.py", bin_path, out_path,
                 "--meta", self.meta_path, "--start-idx", str(power_start_idx)],
                cwd=BASE_DIR,
            )
            # 260913: 파일을 다시 열지 않고, 이미 알고 있는 레코드 크기로 이 파일의 샘플수를 계산해서 누적
            power_start_idx += os.path.getsize(bin_path) // POWER_RECORD_BYTES * POWER_SAMPLES_PER_RECORD
            done += 1
            report()

        vib_start_idx = 0
        for x_path in vib_files:
            out_path = os.path.join(vib_csv, os.path.basename(x_path).replace("_x.bin", ".csv"))
            subprocess.run(
                ["python3", "post_process_vibration.py", x_path, out_path,
                 "--meta", self.meta_path, "--start-idx", str(vib_start_idx)],
                cwd=BASE_DIR,
            )
            vib_start_idx += os.path.getsize(x_path) // VIB_RECORD_BYTES * VIB_SAMPLES_PER_RECORD
            done += 1
            report()

        self.progress_var.set(f"CSV 변환 완료 ({total}/{total}, 100%)")

        extra_done = []

        if self.make_graph_var.get() and power_files:
            self.progress_var.set("시계열 그래프 생성 중...")
            self.root.update()
            first_power_csv = os.path.join(power_csv, os.path.basename(power_files[0]).replace(".bin", ".csv"))
            power_graph = os.path.join(self.result_dir, "power_graph")
            subprocess.run(
                ["python3", "generate_power_graphs.py", first_power_csv, power_graph],
                cwd=BASE_DIR,
            )
            extra_done.append("시계열 그래프")

        if self.make_power_fft_var.get() and power_files:
            self.progress_var.set("전압/전류 FFT 그래프 생성 중...")
            self.root.update()
            first_power_csv = os.path.join(power_csv, os.path.basename(power_files[0]).replace(".bin", ".csv"))
            power_fft_dir = os.path.join(self.result_dir, "power_fft")
            subprocess.run(
                ["python3", "generate_power_fft.py", first_power_csv, power_fft_dir],
                cwd=BASE_DIR,
            )
            extra_done.append("전압/전류 FFT")

        if self.make_vib_fft_var.get() and vib_files:
            self.progress_var.set("진동 FFT 그래프 생성 중...")
            self.root.update()
            first_vib_csv = os.path.join(vib_csv, os.path.basename(vib_files[0]).replace("_x.bin", ".csv"))
            vib_fft_dir = os.path.join(self.result_dir, "vibration_fft")
            subprocess.run(
                ["python3", "generate_vibration_fft.py", first_vib_csv, vib_fft_dir],
                cwd=BASE_DIR,
            )
            extra_done.append("진동 FFT")

        if extra_done:
            self.progress_var.set(f"CSV 변환 완료 + {', '.join(extra_done)} 생성 완료 ({total}/{total}, 100%)")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
