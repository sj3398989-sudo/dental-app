import streamlit as st
from db import get_db
import ui_tabs as ui

# 画面全体設定
st.set_page_config(page_title="AI品質管理カルテ", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")

# スタイル適用
st.markdown("""
<style>
    .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif !important; }
    #MainMenu, header, footer {visibility: hidden;}
    .custom-title { font-size: clamp(1.8rem, 5vw, 2.4rem); font-weight: 700; letter-spacing: -0.02em; color: #1D1D1F; margin-bottom: 20px; }
    .stButton>button[kind="primary"] { border-radius: 12px !important; font-weight: 600 !important; font-size: 15px !important; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.2) !important; transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1) !important; }
    div[data-testid="stVerticalBlock"] > div[style*="border"] { border-radius: 18px !important; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03) !important; padding: 24px !important; border: 1px solid rgba(0,0,0,0.06) !important; background-color: #FFFFFF !important; }
    .metric-card { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); padding: 24px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.6); text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.04); }
    .metric-card h2 { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Rounded", sans-serif; letter-spacing: -0.04em; }
    .alert-card { padding: 14px 18px; border-left: 4px solid #FF3B30; background-color: rgba(255, 59, 48, 0.05); border-radius: 12px; margin-bottom: 10px; color: #1D1D1F; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">🦷 AI品質管理カルテ <span style="font-size: 0.5em; font-weight: 500; color: #8E8E93;">(大阪センター)</span></div>', unsafe_allow_html=True)

db = get_db()
tab1, tab2, tab3, tab4 = st.tabs(["🤖 AI一括", "✍️ 手動", "📊 分析", "📋 管理"])

# 各タブの描画処理を呼び出し
with tab1: ui.render_tab1(db)
with tab2: ui.render_tab2(db)
with tab3: ui.render_tab3()
with tab4: ui.render_tab4(db)
