#!/bin/bash
# 데이터 수집기 GUI 실행 스크립트 (바탕화면 아이콘이 이 스크립트를 실행함)
cd "$(dirname "$0")"

# 260913: 이전 세션이 비정상 종료되어 남아있을 수 있는 프로세스/임시파일을
# 매번 실행 전에 정리 - 포트 충돌/자원 경합 방지
sudo -n pkill -9 openocd 2>/dev/null
pkill -9 -f collect_power.py 2>/dev/null
pkill -9 -f collect_vibration.py 2>/dev/null
pkill -9 -f generate_power_fft.py 2>/dev/null
pkill -9 -f generate_vibration_fft.py 2>/dev/null
pkill -9 -f generate_power_graphs.py 2>/dev/null
rm -f /tmp/power_bank_tmp.bin /tmp/vib_x_tmp.bin /tmp/vib_y_tmp.bin /tmp/vib_z_tmp.bin
sleep 1  # 포트가 완전히 풀릴 시간을 줌

python3 oda_gui.py
