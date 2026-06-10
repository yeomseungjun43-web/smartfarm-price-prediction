
import requests
import xml.etree.ElementTree as ET
import sqlite3
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from tensorflow.keras.models import load_model

def update_db():
    print(f"데이터 업데이트 시작... ({datetime.today().strftime('%Y-%m-%d')})")

    items = {
        "딸기 설향":       {"code": "22607", "unit_qty": "2",  "unit_cd": "01"},
        "딸기 죽향":       {"code": "22609", "unit_qty": "2",  "unit_cd": "01"},
        "딸기(일반)":      {"code": "22600", "unit_qty": "2",  "unit_cd": "01"},
        "대추방울토마토":   {"code": "22504", "unit_qty": "3",  "unit_cd": "01"},
        "방울토마토(일반)": {"code": "22502", "unit_qty": "5",  "unit_cd": "01"},
        "완숙토마토":      {"code": "22511", "unit_qty": "5",  "unit_cd": "01"},
        "토마토":          {"code": "22500", "unit_qty": "10", "unit_cd": "01"},
    }

    url = "http://www.garak.co.kr/homepage/publicdata/dataXmlOpen.do"
    today = datetime.today().strftime("%Y%m%d")
    week_ago = (datetime.today() - timedelta(days=7)).strftime("%Y%m%d")

    conn = sqlite3.connect("스마트팜가격예측.db")
    cursor = conn.cursor()
    new_count = 0

    # 1. 가격 데이터 업데이트
    for name, info in items.items():
        params = {
            "id": "8257",
            "passwd": "seungjun43!",
            "dataid": "data53",
            "pagesize": "10",
            "pageidx": "1",
            "portal.templet": "false",
            "p_fymd": week_ago,
            "p_tymd": today,
            "d_cd": "2",
            "p_pum_cd": info["code"],
            "p_unit_qty": info["unit_qty"],
            "p_unit_cd": info["unit_cd"],
            "p_grade": "0",
            "p_pos_gubun": "1"
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            content = response.content.decode("utf-8")
            root = ET.fromstring(content)
            for item in root.findall("list"):
                avg = item.findtext("AVG_0")
                ymd = item.findtext("YMD")
                if avg and ymd:
                    exists = cursor.execute(
                        "SELECT COUNT(*) FROM 가격데이터 WHERE 날짜=? AND 품목명=?",
                        (ymd, name)
                    ).fetchone()[0]
                    if not exists:
                        분류 = "딸기" if "딸기" in name else "토마토"
                        cursor.execute(
                            "INSERT INTO 가격데이터 (날짜, 작물분류, 품목명, 평균가) VALUES (?,?,?,?)",
                            (ymd, 분류, name, float(avg))
                        )
                        new_count += 1
                        print(f"  가격 추가: {name} {ymd} - {float(avg):,.0f}원")
        except Exception as e:
            print(f"  가격 오류 ({name}): {e}")

    # 2. 기상 데이터 업데이트 (기온 + 강수량 + 기타 변수)
    try:
        service_key = "3d21bc5fa5b32de6fe888528b993186e42796f00fe9fdfc65d9b89795475dd92"
        yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
        temp_url = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
        temp_params = {
            "serviceKey": service_key,
            "pageNo": "1",
            "numOfRows": "10",
            "dataType": "JSON",
            "dataCd": "ASOS",
            "dateCd": "DAY",
            "startDt": week_ago,
            "endDt": yesterday,
            "stnIds": "108"
        }
        response = requests.get(temp_url, params=temp_params, timeout=10)
        result = response.json()["response"]
        if "body" in result:
            for item in result["body"]["items"]["item"]:
                date_str = item["tm"].replace("-", "")
                avg_ta = item.get("avgTa", "")      # 평균기온
                sum_rn = item.get("sumRn", "") or "0"  # 강수량
                avg_ws = item.get("avgWs", "") or "0"  # 평균풍속
                sum_ss = item.get("sumSs", "") or "0"  # 일조량

                if avg_ta:
                    # 기온데이터 테이블 업데이트
                    exists = cursor.execute(
                        "SELECT COUNT(*) FROM 기온데이터 WHERE 날짜=?",
                        (date_str,)
                    ).fetchone()[0]
                    if not exists:
                        cursor.execute(
                            "INSERT INTO 기온데이터 (날짜, 평균기온) VALUES (?,?)",
                            (date_str, float(avg_ta))
                        )
                        print(f"  기온 추가: {date_str} - {avg_ta}℃")

                    # 서울기상_전체.csv 업데이트
                    try:
                        weather_df = pd.read_csv("서울기상_전체.csv", encoding="utf-8-sig")
                        if date_str not in weather_df["날짜"].astype(str).values:
                            new_row = {
                                "날짜": date_str,
                                "평균기온": float(avg_ta) if avg_ta else None,
                                "강수량": float(sum_rn) if sum_rn else 0,
                                "평균풍속": float(avg_ws) if avg_ws else 0,
                                "최대풍속": float(item.get("maxWs", "") or 0),
                                "일조량": float(sum_ss) if sum_ss else 0,
                                "일사량": float(item.get("sumGsr", "") or 0),
                                "온도교차": float(item.get("maxTa", 0) or 0) - float(item.get("minTa", 0) or 0),
                                "최고기온": float(item.get("maxTa", "") or 0),
                                "최저기온": float(item.get("minTa", "") or 0),
                            }
                            weather_df = pd.concat([weather_df, pd.DataFrame([new_row])], ignore_index=True)
                            weather_df.to_csv("서울기상_전체.csv", index=False, encoding="utf-8-sig")
                            print(f"  기상 추가: {date_str} - 기온 {avg_ta}℃, 강수량 {sum_rn}mm")
                    except Exception as e:
                        print(f"  기상 CSV 오류: {e}")

    except Exception as e:
        print(f"  기상 오류: {e}")

    conn.commit()

    # 3. 실제 가격으로 예측결과 업데이트
    rows = cursor.execute("""
        SELECT DISTINCT 품목명, 예측날짜 FROM 예측결과
        WHERE 실제가격 IS NULL
    """).fetchall()

    for 품목명, 예측날짜 in rows:
        actual = cursor.execute("""
            SELECT 평균가 FROM 가격데이터
            WHERE 품목명=? AND 날짜=?
        """, (품목명, 예측날짜)).fetchone()
        if actual:
            cursor.execute("""
                UPDATE 예측결과 SET 실제가격=?
                WHERE 품목명=? AND 예측날짜=?
            """, (actual[0], 품목명, 예측날짜))
            print(f"  실제가격 업데이트: {품목명} {예측날짜} - {actual[0]:,.0f}원")

    conn.commit()

    # 4. 자동 예측 저장
    print("\n자동 예측 시작...")
    auto_predict(cursor, conn)

    conn.commit()
    conn.close()
    print(f"\n업데이트 완료! 새로운 가격 데이터 {new_count}개 추가됨")
    return new_count

def auto_predict(cursor, conn):
    ITEMS = {
        "딸기 설향":       "딸기_설향",
        "딸기 죽향":       "딸기_죽향",
        "딸기(일반)":      "딸기일반",
        "대추방울토마토":   "대추방울토마토",
        "방울토마토(일반)": "방울토마토일반",
        "완숙토마토":      "완숙토마토",
        "토마토":          "토마토",
    }

    SEQ_LEN = 30
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    temp_df = pd.read_sql("SELECT * FROM 기온데이터", conn)
    temp_df["날짜"] = pd.to_datetime(temp_df["날짜"], format="mixed")
    temp_df["평균기온"] = pd.to_numeric(temp_df["평균기온"], errors="coerce")

    try:
        weather_df = pd.read_csv("서울기상_전체.csv", encoding="utf-8-sig")
        weather_df["날짜"] = pd.to_datetime(weather_df["날짜"].astype(str), format="%Y%m%d", errors="coerce")
        weather_df["강수량"] = pd.to_numeric(weather_df["강수량"], errors="coerce").fillna(0)
    except:
        weather_df = None

    price_df = pd.read_sql("SELECT * FROM 가격데이터", conn)
    price_df["날짜"] = pd.to_datetime(price_df["날짜"].astype(str), format="%Y%m%d", errors="coerce")
    price_df["평균가"] = pd.to_numeric(price_df["평균가"], errors="coerce")

    for item_name, safe_name in ITEMS.items():
        try:
            model = load_model(f"models/{safe_name}.keras", compile=False)
            with open(f"models/{safe_name}_scaler.pkl", "rb") as f:
                scaler = pickle.load(f)
            with open(f"models/{safe_name}_features.pkl", "rb") as f:
                features = pickle.load(f)

            df = price_df[price_df["품목명"] == item_name].sort_values("날짜").reset_index(drop=True)
            df = df.merge(temp_df[["날짜", "평균기온"]], on="날짜", how="left")

            if weather_df is not None and "강수량" in features:
                df = df.merge(weather_df[["날짜", "강수량"]], on="날짜", how="left")
                df["강수량"] = df["강수량"].fillna(0)
                df["7일누적강수량"] = df["강수량"].rolling(7).sum().fillna(0)

            df["월"] = df["날짜"].dt.month
            df["전년도가격"] = df["평균가"].shift(365)
            df["7일평균가"] = df["평균가"].rolling(7).mean()
            df["30일평균가"] = df["평균가"].rolling(30).mean()
            df["전일가격"] = df["평균가"].shift(1)
            df["가격변화율"] = df["평균가"].pct_change()
            df["7일내_폭염발생"] = (df["평균기온"] >= 33).rolling(7).max().fillna(0).astype(int)
            df["환절기여부"] = df["월"].isin([9, 10]).astype(int)
            df["봄_환절기여부"] = df["월"].isin([3, 4]).astype(int)
            df = df.dropna().reset_index(drop=True)

            if len(df) < SEQ_LEN:
                continue

            last_date = df["날짜"].iloc[-1]
            preds = []
            future_dates = []
            current_df = df.copy()

            for i in range(30):
                next_date = last_date + timedelta(days=i+1)
                future_dates.append(next_date)

                data = current_df[features].values
                scaled = scaler.transform(data)
                seq = scaled[-SEQ_LEN:].reshape(1, SEQ_LEN, len(features))

                pred_scaled = model.predict(seq, verbose=0)[0][0]
                dummy = np.zeros((1, len(features)))
                dummy[0, 0] = pred_scaled
                pred_real = scaler.inverse_transform(dummy)[0][0]
                preds.append(pred_real)

                new_row = current_df.iloc[-1].copy()
                new_row["날짜"] = next_date
                new_row["평균가"] = pred_real
                new_row["월"] = next_date.month
                if "전일가격" in features:
                    new_row["전일가격"] = pred_real
                if "7일평균가" in features:
                    new_row["7일평균가"] = np.mean(list(current_df["평균가"].tail(6)) + [pred_real])
                if "30일평균가" in features:
                    new_row["30일평균가"] = np.mean(list(current_df["평균가"].tail(29)) + [pred_real])
                if "가격변화율" in features:
                    prev = current_df["평균가"].iloc[-1]
                    new_row["가격변화율"] = (pred_real - prev) / prev if prev != 0 else 0
                current_df = pd.concat([current_df, pd.DataFrame([new_row])], ignore_index=True)

            for date, price in zip(future_dates, preds):
                date_str = date.strftime("%Y%m%d")
                exists = cursor.execute("""
                    SELECT COUNT(*) FROM 예측결과
                    WHERE 품목명=? AND 예측날짜=? AND DATE(예측일시)=DATE(?)
                """, (item_name, date_str, now)).fetchone()[0]
                if not exists:
                    cursor.execute("""
                        INSERT INTO 예측결과 (예측일시, 품목명, 예측날짜, 예측가격, 실제가격)
                        VALUES (?, ?, ?, ?, NULL)
                    """, (now, item_name, date_str, round(price, 0)))

            print(f"  자동예측 저장: {item_name} 30일치")

        except Exception as e:
            print(f"  자동예측 오류 ({item_name}): {e}")

if __name__ == "__main__":
    update_db()
