"""Tab 2: 手動登録（画像は扱わない・純粋なデータ入力フォーム）。"""

from datetime import date

import streamlit as st

from config import (
    MATERIAL_LIST, SCORE_MAX, SCORE_MIN, SCORE_OPTIMAL, SHEET_TYPE_LIST, TYPE_LIST,
)
from database import get_db, save_single_evaluation


def render():
    st.markdown("### ✍️ 新規データの手動入力")
    st.info("⌨️ 各種項目を入力して、手動で登録ボタンを押して下さい。")
    with st.container(border=True):
        with st.form("manual_entry_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                m_clinic = st.text_input("🏥 医院名 (必須)")
                m_slip = st.text_input("📝 伝票番号 (必須)")
                m_date = st.date_input("📅 完成日", value=date.today())
                m_stype = st.selectbox("📄 シート種別", SHEET_TYPE_LIST)
            with c2:
                m_type = st.selectbox("🦷 種別", TYPE_LIST)
                m_material = st.selectbox("💎 材料", MATERIAL_LIST)
                m_pos = st.text_input("📍 部位")
                m_con = st.slider("コンタクト", SCORE_MIN, SCORE_MAX, SCORE_OPTIMAL)
                m_bit = st.slider("バイト", SCORE_MIN, SCORE_MAX, SCORE_OPTIMAL)
                m_fit = st.slider("適合", SCORE_MIN, SCORE_MAX, SCORE_OPTIMAL)
            m_com = st.text_area("💬 コメント")

            if st.form_submit_button("手動で登録する", type="primary"):
                if not m_clinic or not m_slip:
                    st.error("⚠️ 医院名と伝票番号は必須入力です。")
                elif get_db():
                    save_single_evaluation({
                        "clinic_name": m_clinic, "slip_number": m_slip,
                        "completion_date": m_date.isoformat(), "sheet_type": m_stype,
                        "restoration_type": m_type, "material": m_material,
                        "tooth_position": m_pos, "contact": m_con, "bite": m_bit,
                        "fit": m_fit, "comments": m_com,
                    })
                    st.toast("手動登録が完了しました！入力欄はリセットされました。", icon="✅")
