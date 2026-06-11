
import streamlit as st
import pandas as pd
import numpy as np
import pickle
import matplotlib.pyplot as plt
import matplotlib
from keras.models import load_model
from datetime import datetime, timedelta
import sqlite3
import importlib.util
import warnings
warnings.filterwarnings("ignore")

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

st.set_page_config(
    page_title="스마트팜 가격 예측 시스템",
    page_icon="🌱",
    layout="wide"
)

ITEMS = {
    "🍓 딸기 설향": "딸기_설향",
    "🍓 딸기 죽향": "딸기_죽향",
    "🍓 딸기(일반)": "딸기일반",
    "🍅 대추방울토마토": "대추방울토마토",
    "🍅 방울토마토(일반)": "방울토마토일반",
    "🍅 완숙토마토": "완숙토마토",
    "🍅 토마토": "토마토",
}

UNITS = {
    "딸기_설향": "2kg 상자",
    "딸기_죽향": "2kg 상자",
    "딸기일반": "2kg 상자",
    "대추방울토마토": "3kg 상자",
    "방울토마토일반": "5kg 상자",
    "완숙토마토": "5kg 상자",
    "토마토": "10kg 상자",
}

R2_SCORES = {
    "딸기_설향": 0.8851,
    "딸기_죽향": 0.7009,
    "딸기일반": 0.6992,
    "대추방울토마토": 0.6706,
    "방울토마토일반": 0.6368,
    "완숙토마토": 0.7984,
    "토마토": 0.6912,
}

SEQ_LEN = 30

@st.cache_resource
def load_model_and_scaler(safe_name):
    model = load_model(f"models/{safe_name}.keras")
    with open(f"models/{safe_name}_scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    with open(f"models/{safe_name}_features.pkl", "rb") as f:
        features = pickle.load(f)
    df = pd.read_csv(f"models/{safe_name}_data.csv", encoding="utf-8-sig")
    df["날짜"] = pd.to_datetime(df["날짜"])
    return model, scaler, features, df

def predict_future_rolling(model, scaler, features, df, days=30):
    """
    롤링 예측: 실제 데이터가 있는 날은 실제값 사용,
    없는 날만 예측값으로 채움 → 오차 누적 최소화
    """
    last_date = df["날짜"].iloc[-1]
    future_dates = [last_date + timedelta(days=i+1) for i in range(days)]
    preds = []
    is_actual = []  # 실제값인지 예측값인지 표시

    # 현재 데이터 복사
    current_df = df.copy()

    for i, target_date in enumerate(future_dates):
        # 실제 데이터에 해당 날짜가 있으면 실제값 사용
        actual_row = current_df[current_df["날짜"] == target_date]

        if len(actual_row) > 0 and not pd.isna(actual_row["평균가"].values[0]):
            # 실제값 사용!
            actual_price = actual_row["평균가"].values[0]
            preds.append(actual_price)
            is_actual.append(True)
        else:
            # 실제값 없으면 예측
            data = current_df[features].values
            scaled = scaler.transform(data)
            seq = scaled[-SEQ_LEN:].reshape(1, SEQ_LEN, len(features))

            pred_scaled = model.predict(seq, verbose=0)[0][0]
            dummy = np.zeros((1, len(features)))
            dummy[0, 0] = pred_scaled
            pred_real = scaler.inverse_transform(dummy)[0][0]
            preds.append(pred_real)
            is_actual.append(False)

            # 예측값을 다음 예측을 위해 데이터에 추가
            new_row = current_df.iloc[-1].copy()
            new_row["날짜"] = target_date
            new_row["평균가"] = pred_real
            new_row["월"] = target_date.month
            if "전일가격" in features:
                new_row["전일가격"] = pred_real
            if "7일평균가" in features:
                recent = list(current_df["평균가"].tail(6)) + [pred_real]
                new_row["7일평균가"] = np.mean(recent)
            if "30일평균가" in features:
                recent30 = list(current_df["평균가"].tail(29)) + [pred_real]
                new_row["30일평균가"] = np.mean(recent30)
            if "가격변화율" in features:
                prev = current_df["평균가"].iloc[-1]
                new_row["가격변화율"] = (pred_real - prev) / prev if prev != 0 else 0

            current_df = pd.concat([current_df, pd.DataFrame([new_row])], ignore_index=True)

    return future_dates, preds, is_actual

def save_predictions(품목명, future_dates, preds):
    conn = sqlite3.connect("스마트팜가격예측.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for date, price in zip(future_dates, preds):
        cursor.execute("""
            INSERT OR IGNORE INTO 예측결과 (예측일시, 품목명, 예측날짜, 예측가격, 실제가격)
            VALUES (?, ?, ?, ?, NULL)
        """, (now, 품목명, date.strftime("%Y%m%d"), round(price, 0)))
    conn.commit()
    conn.close()

def update_actual_prices():
    conn = sqlite3.connect("스마트팜가격예측.db")
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

def run_update():
    spec = importlib.util.spec_from_file_location("update_data", "update_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.update_db()

# ─── UI ───
st.title("🌱 스마트팜 농산물 가격 예측 시스템")
st.markdown("**출하 시기 결정을 위한 AI 가격 예측 도구**")

with st.sidebar:
    st.markdown("## ⚙️ 설정")
    st.markdown(f"📅 오늘: **{datetime.today().strftime('%Y년 %m월 %d일')}**")
    st.markdown("---")
    if st.button("📡 최신 데이터 업데이트", use_container_width=True):
        with st.spinner("최신 데이터 수집 중..."):
            try:
                run_update()
                update_actual_prices()
                st.cache_resource.clear()
                st.success("✅ 업데이트 완료!")
            except Exception as e:
                st.error(f"오류: {e}")
    st.markdown("---")
    st.markdown("### 📊 모델 성능 (R²)")
    perf_df = pd.DataFrame({
        "품목": ["딸기 설향", "완숙토마토", "딸기 죽향", "딸기(일반)", "대추방울토마토", "토마토", "방울토마토"],
        "R²": [0.8851, 0.7984, 0.7009, 0.6992, 0.6706, 0.6912, 0.6368],
    })
    st.dataframe(perf_df, use_container_width=True, hide_index=True)

tab1, tab2 = st.tabs(["🔮 가격 예측", "📊 예측 검증"])

with tab1:
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected = st.selectbox("📦 품목 선택", list(ITEMS.keys()))
    with col2:
        days = st.selectbox("📅 예측 기간", [7, 14, 30], index=2,
                           format_func=lambda x: f"{x}일")
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        predict_btn = st.button("🔮 예측하기", use_container_width=True, type="primary")

    safe_name = ITEMS[selected]
    unit = UNITS[safe_name]
    r2_val = R2_SCORES[safe_name]

    if predict_btn:
        with st.spinner("AI 모델 예측 중..."):
            try:
                model, scaler, features, df = load_model_and_scaler(safe_name)

                # 롤링 예측 사용!
                future_dates, preds, is_actual = predict_future_rolling(
                    model, scaler, features, df, days)

                # 예측 결과 저장
                item_name = selected.split(" ", 1)[1]
                save_predictions(item_name, future_dates, preds)

                st.markdown("---")
                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    st.metric("현재 가격", f"{df['평균가'].iloc[-1]:,.0f}원", help=unit)
                with col_b:
                    st.metric("예측 최고가", f"{max(preds):,.0f}원",
                             delta=f"+{max(preds)-df['평균가'].iloc[-1]:,.0f}원")
                with col_c:
                    st.metric("예측 최저가", f"{min(preds):,.0f}원",
                             delta=f"{min(preds)-df['평균가'].iloc[-1]:,.0f}원")
                with col_d:
                    best_day = future_dates[preds.index(max(preds))]
                    st.metric("최고가 예상일", best_day.strftime("%m월 %d일"))

                # 실제값 vs 예측값 비율 표시
                actual_count = sum(is_actual)
                if actual_count > 0:
                    st.success(f"✅ {days}일 중 {actual_count}일은 실제 데이터 사용 → 오차 최소화!")

                st.info(f"📈 예측 정확도 (R²): **{r2_val:.4f}** "
                       f"({'매우 높음 🔥' if r2_val >= 0.8 else '높음 ✅' if r2_val >= 0.7 else '양호 👍'})")

                fig, ax = plt.subplots(figsize=(12, 5))
                recent = df.tail(60)
                ax.plot(recent["날짜"], recent["평균가"],
                       color="#2E86AB", linewidth=2, label="실제 가격 (최근 60일)")

                # 실제값과 예측값 구분해서 표시
                actual_dates = [d for d, a in zip(future_dates, is_actual) if a]
                actual_prices = [p for p, a in zip(preds, is_actual) if a]
                pred_dates = [d for d, a in zip(future_dates, is_actual) if not a]
                pred_prices = [p for p, a in zip(preds, is_actual) if not a]

                if actual_dates:
                    ax.plot(actual_dates, actual_prices,
                           color="#2ECC71", linewidth=2.5,
                           marker="o", markersize=5, label="실제 확인된 가격")
                if pred_dates:
                    ax.plot(pred_dates, pred_prices,
                           color="#E84855", linewidth=2.5, linestyle="--",
                           marker="o", markersize=4, label="AI 예측 가격")

                best_idx = preds.index(max(preds))
                ax.annotate(f"최고 {max(preds):,.0f}원",
                           xy=(future_dates[best_idx], max(preds)),
                           xytext=(10, 15), textcoords="offset points",
                           fontsize=10, color="#E84855",
                           arrowprops=dict(arrowstyle="->", color="#E84855"))

                ax.axvline(x=df["날짜"].iloc[-1], color="gray",
                          linestyle=":", linewidth=1.5, label="오늘")
                ax.fill_between(future_dates, preds, alpha=0.1, color="#E84855")
                ax.set_title(f"{selected} 가격 예측 ({days}일)", fontsize=14, fontweight="bold")
                ax.set_xlabel("날짜")
                ax.set_ylabel(f"가격 (원 / {unit})")
                ax.legend(fontsize=10)
                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.tight_layout()
                st.pyplot(fig)

                st.markdown("### 📋 일별 예측 가격")
                pred_df = pd.DataFrame({
                    "날짜": [d.strftime("%Y-%m-%d") for d in future_dates],
                    f"예측 가격 (원/{unit})": [f"{p:,.0f}" for p in preds],
                    "구분": ["✅ 실제값" if a else "🔮 예측값" for a in is_actual],
                    "현재 대비": [f"+{p-df['평균가'].iloc[-1]:,.0f}원" if p >= df["평균가"].iloc[-1]
                                else f"{p-df['평균가'].iloc[-1]:,.0f}원" for p in preds]
                })
                st.dataframe(pred_df, use_container_width=True, hide_index=True)

                st.markdown("### 💡 출하 추천")
                if max(preds) > df["평균가"].iloc[-1] * 1.1:
                    st.success(f"✅ **{best_day.strftime('%m월 %d일')}** 출하를 추천합니다! "
                              f"현재보다 **{max(preds)-df['평균가'].iloc[-1]:,.0f}원** 높게 판매 가능합니다.")
                elif min(preds) < df["평균가"].iloc[-1] * 0.9:
                    st.warning("⚠️ 향후 가격 하락이 예상됩니다. 빠른 출하를 고려해보세요.")
                else:
                    st.info("ℹ️ 향후 가격이 비교적 안정적으로 유지될 것으로 예상됩니다.")

            except Exception as e:
                st.error(f"오류 발생: {e}")
    else:
        st.info("👆 품목과 예측 기간을 선택하고 예측하기 버튼을 눌러주세요!")

with tab2:
    st.markdown("### 📊 예측 vs 실제 가격 검증")
    update_actual_prices()

    conn = sqlite3.connect("스마트팜가격예측.db")
    verified_df = pd.read_sql("""
        SELECT 품목명, 예측날짜, 예측가격, 실제가격,
               ABS(예측가격 - 실제가격) as 오차,
               ROUND(ABS(예측가격 - 실제가격) / 실제가격 * 100, 1) as 오차율
        FROM 예측결과
        WHERE 실제가격 IS NOT NULL
        ORDER BY 예측날짜 DESC
    """, conn)
    all_pred_df = pd.read_sql("""
        SELECT 품목명, 예측날짜, 예측가격, 실제가격
        FROM 예측결과
        ORDER BY 예측날짜 DESC
        LIMIT 100
    """, conn)
    conn.close()

    if len(verified_df) > 0:
        items_list = ["전체"] + list(verified_df["품목명"].unique())
        selected_item = st.selectbox("품목 선택", items_list)
        filtered_df = verified_df if selected_item == "전체" else verified_df[verified_df["품목명"] == selected_item]

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("검증된 예측 수", f"{len(filtered_df)}개")
        with col_b:
            avg_err = filtered_df["오차율"].mean()
            st.metric("평균 오차율", f"{avg_err:.1f}%")
        with col_c:
            st.metric("평균 정확도", f"{100-avg_err:.1f}%")

        if len(filtered_df) > 1:
            fig, ax = plt.subplots(figsize=(12, 5))
            filtered_df["예측날짜"] = pd.to_datetime(filtered_df["예측날짜"], format="%Y%m%d")
            filtered_df = filtered_df.sort_values("예측날짜")
            ax.plot(filtered_df["예측날짜"], filtered_df["실제가격"],
                   color="#2E86AB", linewidth=2, marker="o", label="실제 가격")
            ax.plot(filtered_df["예측날짜"], filtered_df["예측가격"],
                   color="#E84855", linewidth=2, marker="s", linestyle="--", label="예측 가격")
            ax.set_title("예측 가격 vs 실제 가격 비교", fontsize=14, fontweight="bold")
            ax.set_ylabel("가격 (원)")
            ax.legend(fontsize=10)
            ax.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            st.pyplot(fig)

        st.markdown("### 📋 상세 검증 결과")
        display_df = filtered_df.copy()
        display_df["예측날짜"] = pd.to_datetime(display_df["예측날짜"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        display_df["예측가격"] = display_df["예측가격"].apply(lambda x: f"{x:,.0f}원")
        display_df["실제가격"] = display_df["실제가격"].apply(lambda x: f"{x:,.0f}원")
        display_df["오차"] = display_df["오차"].apply(lambda x: f"{x:,.0f}원")
        display_df["오차율"] = display_df["오차율"].apply(lambda x: f"{x:.1f}%")
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("아직 검증할 데이터가 없어요! 예측하기를 먼저 실행하고 며칠 후 확인해보세요 😊")

    st.markdown("### 📝 전체 예측 기록")
    if len(all_pred_df) > 0:
        all_pred_df["예측날짜"] = pd.to_datetime(all_pred_df["예측날짜"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        all_pred_df["예측가격"] = all_pred_df["예측가격"].apply(lambda x: f"{x:,.0f}원")
        all_pred_df["실제가격"] = all_pred_df["실제가격"].apply(
            lambda x: f"{x:,.0f}원" if pd.notna(x) else "확인 중...")
        st.dataframe(all_pred_df, use_container_width=True, hide_index=True)
    else:
        st.info("예측 기록이 없어요!")

st.markdown("---")
st.caption("빅데이터분석및응용 | 전북대학교 빅데이터학부 | 2026")
