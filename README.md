# ODA Measure - 전력/진동 동시 데이터 수집 시스템

STM32U575 MCU 2대(전력측정용 ADS131M08, 진동측정용 IIS3DWB)를 ST-LINK + OpenOCD를 통해
라즈베리파이에서 실시간으로 손실 없이 동시에 수집하는 시스템입니다.

## 1. 필요한 하드웨어

- 라즈베리파이 (모니터 연결 권장, GUI 실행에 디스플레이 필요)
- ST-LINK V3 2개 (전력용 1개, 진동용 1개)
- 전력측정 MCU 보드 (ADS131M08 기반, `PowerMeasurePCB_MCU_DumpGather` 펌웨어)
- 진동측정 MCU 보드 (IIS3DWB 기반, `STM32U575CIT6_LED_Toggle_for16g` 펌웨어)

## 2. 라즈베리파이 최초 설정

### 2.1 필수 패키지 설치

```bash
sudo apt update
sudo apt install openocd python3-tk python3-pil python3-pil.imagetk fonts-nanum -y
pip3 install numpy matplotlib
```

### 2.2 이 저장소 클론

```bash
cd ~/Desktop
git clone <이 저장소 URL> ODA_Measure
cd ODA_Measure/src
chmod +x run_gui.sh
```

### 2.3 ST-LINK 시리얼 번호 확인 및 반영 (필수)

두 ST-LINK를 각각 하나씩만 연결한 상태로 시리얼 번호를 확인합니다.

```bash
lsusb -v -d 0483: 2>/dev/null | grep -i serial
```

`oda_gui.py` 상단의 아래 두 줄을 실제 확인한 시리얼 번호로 수정합니다.

```python
POWER_SERIAL = "여기에_전력용_시리얼"
VIB_SERIAL = "여기에_진동용_시리얼"
```

### 2.4 진동 프로세스 실시간 우선순위(chrt) 비밀번호 없이 쓰기 설정

```bash
which chrt   # 보통 /usr/bin/chrt
sudo visudo -f /etc/sudoers.d/chrt_nopasswd
```

파일에 아래 한 줄 추가 (계정명은 실제 사용 계정으로):

```
power ALL=(ALL) NOPASSWD: /usr/bin/chrt, /usr/bin/pkill
```

### 2.5 바탕화면 아이콘 등록

`ODA_Measure.desktop`을 `~/Desktop/`에 두고, 안의 `Exec=`, `Icon=` 경로를 실제 계정명/경로로 맞춘 뒤:

```bash
chmod +x ~/Desktop/ODA_Measure.desktop
gio set ~/Desktop/ODA_Measure.desktop metadata::trusted true
```

로고 이미지(`odalogo_horizon.png`)는 `~/Desktop/ODA_Measure/` 바로 밑에 위치해야 GUI 상단에 표시됩니다.

## 3. 실행 방법

바탕화면의 아이콘을 더블클릭하면 됩니다. (`run_gui.sh`가 이전 세션의 잔여 프로세스를 자동 정리한 뒤 GUI를 띄웁니다)

GUI에서:
1. 측정 정보(파일명 등) 입력 — 파일명은 결과 폴더명이 되므로 공백 없이 입력 권장
2. 필요하면 "시계열 그래프 만들기", "전압/전류 FFT 그래프 만들기", "진동 FFT 그래프 만들기" 체크
3. [시작] → 자동으로 OpenOCD 2개 + 수집 스크립트 2개 실행, 상태창에 30초 주기로 누적 샘플수/오버런 여부 표시
4. [종료] → 프로세스 정리 후 CSV 변환(+체크한 그래프) 자동 생성

## 4. 결과물 구조

```
ODA_Measure/result/<측정명>/
  ├─ power_bin/          원시 바이너리 (실시간 저장)
  ├─ power_csv/          변환된 CSV (part001.csv에만 메타데이터 헤더 포함)
  ├─ power_graph/        (체크시) 전압/전류 시계열 그래프 9장
  ├─ power_fft/          (체크시) 전압/전류 FFT 그래프 9장
  ├─ vibration_bin/      원시 바이너리 (x/y/z 별도 파일)
  ├─ vibration_csv/      변환된 CSV
  ├─ vibration_fft/      (체크시) 진동 FFT 그래프 4장
  └─ metadata.json        입력한 측정 정보
```

## 5. 알려진 제약/주의사항

- 전력/진동을 동시에 수집하면, 두 ST-LINK가 같은 USB 컨트롤러/전원을 공유할 경우 드물게
  통신 오류로 인한 데이터 값 오염이 관측된 바 있음 (오버런 카운터에는 안 잡힘). 가능하면
  서로 다른 USB 허브/포트에 분리 연결 권장.
- MCU 펌웨어를 다시 빌드/플래시한 경우, `arm-none-eabi-nm`으로 심볼 주소가 각 수집 스크립트의
  하드코딩된 주소(`ADDR_*`)와 일치하는지 반드시 재확인할 것.
- 진동 CSV의 메타데이터/컬럼 형식(`idx, timestamp, x, y, z`, 탭 구분)은 예전 GitHub 원본 코드의
  `idx, x, y, z` 형식과 다름 (timestamp 컬럼 추가됨) — 기존 후처리 파이프라인과 연동시 주의.
