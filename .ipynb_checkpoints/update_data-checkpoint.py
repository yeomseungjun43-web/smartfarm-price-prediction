
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import sqlite3
from datetime import datetime, timedelta

def get_today_price(pum_cd, unit_qty, unit_cd, name):
    url = "http://www.garak.co.kr/homepage/publicdata/dataXmlOpen.do"
    today = datetime.today().strftime("%Y%m%d")
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")

    params = {
        "id": "8257",
        "passwd": "seungjun43!",
        "dataid": "data53",
        "pagesize": "7",
        "pageidx": "1",
        "portal.templet": "false",
        "p_fymd": yesterday,
        "p_tymd": today,
        "d_cd": "2",
        "p_pum_cd": pum_cd,
        "p_unit_qty": unit_qty,
        "p_unit_cd": unit_cd,
        "p_grade": "0",
        "p_pos_gubun": "1"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        content = response.content.decode("utf-8")
        root = ET.fromstring(content)
        rows = []
        for item in root.findall("list"):
            avg = item.findtext("AVG_0")
            ymd = item.findtext("YMD")
            if avg and ymd:
                rows.append({"날짜": ymd, "품목명": name, "평균가": avg})
        return rows
    except:
        return []

def get_today_temperature():
    """기상청 API에서 오늘 기온 가져오기"""
    import requests
    from datetime import datetime, timedelta

    service_key = "3d21bc5fa5b32de6fe888528b993186e42796f00fe9fdfc65d9b89795475dd92"
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")

    url = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
    params = {
        "serviceKey": service_key,
        "pageNo": "1",
        "numOfRows": "3",
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": yesterday,
        "endDt": yesterday,
        "stnIds": "108"
    }

    try:
        response = requests.get(url, params=params)
        result = response.json()["response"]
        if "body" in result:
            items = result["body"]["items"]["item"]
            return [{"날짜": item["tm"].replace("-",""), "평균기온": item.get("avgTa","")} for item in items]
    except:
        return []

def update_db():
    print(f"📡 실시간 데이터 업데이트 시작... ({datetime.today().strftime('%Y-%m-%d')})")

    # 품목별 최신 가격 수집
    items = {
        "딸기 설향":      {"code": "22607", "unit_qty": "2", "unit_cd": "01"},
        "딸기 죽향":      {"code": "22609", "unit_qty": "2", "unit_cd": "01"},
        "딸기(일반)":     {"code": "22600", "unit_qty": "2", "unit_cd": "01"},
        "대추방울토마토":  {"code": "22504", "unit_qty": "3", "unit_cd": "01"},
        "방울토마토(일반)":{"code": "22502", "unit_qty": "5", "unit_cd": "01"},
        "완숙토마토":     {"code": "22511", "unit_qty": "5", "unit_cd": "01"},
        "토마토":         {"code": "22500", "unit_qty": "10","unit_cd": "01"},
    }

    conn = sqlite3.connect("스마트팜가격예측.db")
    cursor = conn.cursor()
    new_count = 0

    for name, info in items.items():
        rows = get_today_price(info["code"], info["unit_qty"], info["unit_cd"], name)
        for row in rows:
            # 중복 체크 후 삽입
            exists = cursor.execute(
                "SELECT COUNT(*) FROM 가격데이터 WHERE 날짜=? AND 품목명=?",
                (row["날짜"], row["품목명"])
            ).fetchone()[0]

            if not exists:
                cursor.execute(
                    "INSERT INTO 가격데이터 (날짜, 작물분류, 품목명, 평균가) VALUES (?,?,?,?)",
                    (row["날짜"], "딸기" if "딸기" in name else "토마토", name, row["평균가"])
                )
                new_count += 1
                print(f"  ✅ {name} {row['날짜']} - {float(row['평균가']):,.0f}원 추가!")

    # 기온 업데이트
    temps = get_today_temperature()
    for temp in temps:
        exists = cursor.execute(
            "SELECT COUNT(*) FROM 기온데이터 WHERE 날짜=?",
            (temp["날짜"],)
        ).fetchone()[0]
        if not exists and temp["평균기온"]:
            cursor.execute(
                "INSERT INTO 기온데이터 (날짜, 평균기온) VALUES (?,?)",
                (temp["날짜"], temp["평균기온"])
            )
            print(f"  🌡️ 기온 {temp['날짜']} - {temp['평균기온']}℃ 추가!")

    conn.commit()
    conn.close()
    print(f"\n✅ 업데이트 완료! 새로운 데이터 {new_count}개 추가됨")

if __name__ == "__main__":
    update_db()
