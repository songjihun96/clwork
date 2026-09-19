"""
통학 거리 계산.

사용자의 실제 좌표(도로명주소 검색 또는 현재 위치로 얻음)와
학교의 실제 좌표 사이 직선거리만 쓴다.
좌표가 없는 학교는 거리를 계산하지 않는다(억지로 0km로 만들지 않는다).
"""

import math

# 실제로 거르는 기준은 거리(km)다. 그래서 거리를 앞에 두고, 감을 잡기
# 쉬우라고 대중교통 기준 시간을 괄호에 덧붙인다.
#
# 예전에는 시간을 앞에 뒀는데, 속으로는 직선거리로 걸러서 교통이 나쁜
# 곳에서는 '1시간 이내'라 해놓고 두 시간 걸리는 학교가 나왔다.
# 표시와 실제가 어긋나지 않게 순서를 바꿨다.
#
# 시간 환산은 도심 평균(1시간에 약 25km)으로 잡은 어림값이다.
TIME_OPTIONS = [
    {"key": "30m", "label": "10km 이내", "hint": "버스로 약 30분",
     "minutes": 30, "km": 10},
    {"key": "1h", "label": "25km 이내", "hint": "약 1시간",
     "minutes": 60, "km": 25},
    {"key": "1h30", "label": "40km 이내", "hint": "약 1시간 30분",
     "minutes": 90, "km": 40},
    {"key": "2h", "label": "55km 이내", "hint": "약 2시간",
     "minutes": 120, "km": 55},
    {"key": "any", "label": "거리 상관없음", "hint": "전국에서 찾기",
     "minutes": None, "km": None},
]

TIME_BY_KEY = {opt["key"]: opt for opt in TIME_OPTIONS}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """두 위경도 사이 직선거리(km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def school_distance_km(user_lat, user_lng, school):
    """
    사용자 좌표에서 학교까지의 직선거리(km).
    사용자 좌표나 학교 좌표가 없으면 None.
    """
    if user_lat is None or user_lng is None:
        return None
    if school.latitude is None or school.longitude is None:
        return None
    return haversine_km(user_lat, user_lng, school.latitude, school.longitude)


def within_commute(user_lat, user_lng, school, limit_km) -> bool:
    """
    통학 가능 여부.
    - limit_km가 None(거리 상관없음)이면 항상 True.
    - 그 외에는 거리를 잴 수 있고 한도 안일 때만 True.
      좌표가 없어 거리를 못 재는 학교는 통학권 판단에서 제외(False).
    """
    if limit_km is None:
        return True
    dist = school_distance_km(user_lat, user_lng, school)
    if dist is None:
        return False
    return dist <= limit_km
