"""
전력/진동 CSV 공통 - 메타데이터 헤더(펌프 성능시험 정보) 읽기/쓰기 유틸.
metadata.json은 GUI가 측정 시작시 result/<측정명>/ 밑에 만들어두는 것을 전제로 함.
"""
import json

# 순서 고정 (예전 GUI 입력창 순서와 동일)
META_FIELDS = [
    "날짜", "파일명", "데이터종류", "모터RPM", "주파수", "측정시간(분)",
    "토출량", "전양정", "축동력", "흡입압력", "토출압력",
    "전류", "효율", "역률", "전압", "온도1", "온도2",
]


def load_metadata(meta_path):
    """metadata.json을 읽어서 dict로 반환. 없으면 None."""
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def write_metadata_header(f, meta: dict):
    """CSV 파일 객체 f에 key\\tvalue 형식 헤더 + 빈 줄을 씀. (part001에만 호출할 것)"""
    for key in META_FIELDS:
        value = meta.get(key, "")
        f.write(f"{key}\t{value}\n")
    f.write("\n")


def is_first_part(bin_path):
    """파일명에 part001이 포함되어 있으면 True (메타데이터 헤더를 넣어야 하는 파일인지 판단)"""
    return "part001" in bin_path
