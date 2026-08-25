"""AI品質管理カルテ（大阪センター） - エントリーポイント。

役割: テーマ設定 → CSS適用 → ログイン認証 → データ取得 → 各タブの呼び出し。
個別の処理は config / database / ai_service / tabs 配下の各モジュールに分離している。
"""

# ==========================================
# ★ テーマ設定は「streamlit を import する前」に実行する必要がある
#    （.streamlit/config.toml を先に生成するため）
# ==========================================
from config import setup_theme

is_new_theme_created = setup_theme()

import hmac
import time

import streamlit as st

from config import CUSTOM_CSS, esc, is_admin
from database import load_all_evaluations
from tabs import tab1_ai_register, tab2_manual, tab3_dashboard, tab4_management

# ==========================================
# 1. アプリケーション初期設定 & CSS
# ==========================================
st.set_page_config(page_title="AI品質管理カルテ", page_icon="🦷", layout="wide",
                   initial_sidebar_state="collapsed")

if is_new_theme_created:
    st.info("🎨 新しいテーマカラー（ブルー）を設定しました。完全に反映させるため、ブラウザを「再読み込み（F5キー）」してください。")

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ==========================================
# 2. 🔐 ログイン認証処理（セキュリティガード）
# ==========================================
def secure_equals(a, b):
    """タイミング攻撃に強い文字列比較（日本語などの非ASCII文字にも対応）。"""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def check_password():
    """未認証の場合はログインフォームを表示し、認証が通るまでTrueを返さない"""
    def password_entered():
        users = st.secrets.get("passwords", {})
        input_user = st.session_state.get("login_username", "")
        input_pass = st.session_state.get("login_password", "")

        # ユーザーが存在しない場合もダミー値と比較し、処理時間の差から
        # 「ユーザー名の存在有無」が推測されないようにする
        user_exists = input_user in users
        expected_pass = users[input_user] if user_exists else ""
        password_matched = secure_equals(input_pass, expected_pass)

        if user_exists and password_matched:
            st.session_state["password_correct"] = True
            st.session_state["current_user"] = input_user
            del st.session_state["login_password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    # ログイン画面
    st.markdown('<div class="custom-title">🦷 AI品質管理カルテ</div>', unsafe_allow_html=True)
    st.caption("(大阪センター)")
    st.markdown("### 🔐 関係者ログイン")
    st.caption("このシステムは関係者専用です。")

    with st.container(border=True):
        with st.form("login_form"):
            st.text_input("ユーザー名（ID）", key="login_username", placeholder="ID を入力", label_visibility="collapsed")
            st.text_input("パスワード", type="password", key="login_password", placeholder="パスワードを入力", label_visibility="collapsed")
            st.form_submit_button("ログインする", on_click=password_entered, type="primary")

    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("⚠️ ユーザー名またはパスワードが正しくありません。")

    return False


# ログインしていなければここで処理を完全停止
if not check_password():
    st.stop()

# ==========================================
# 3. 画面ヘッダー ＆ ログアウトボタン
# ==========================================
# 患者名（個人情報）はシステム全体で取得・保存・表示しないため、
# 患者名マスク用の「プライバシーモード」トグルは廃止している。
head_col1, head_col2, head_col3 = st.columns([2, 1, 0.8])
with head_col1:
    current_user = esc(st.session_state.get("current_user", ""))
    role_label = "管理者" if is_admin() else "一般スタッフ"
    st.markdown(f'<div class="custom-title">🦷 AI品質管理カルテ</div>', unsafe_allow_html=True)
    st.caption(f"(大阪センター) | 👤 {current_user}（{role_label}）")

with head_col3:
    st.markdown("<div style='height: 26px;'></div>", unsafe_allow_html=True)
    if st.button("ログアウト", key="logout_btn"):
        for key in ("password_correct", "current_user"):
            st.session_state.pop(key, None)
        st.rerun()

# ==========================================
# 4. 全体データの一括取得
# ==========================================
global_df = load_all_evaluations()

# ==========================================
# 5. セッション初期化
# ==========================================
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = "uploader_" + str(time.time())

if "nav_mode" not in st.session_state:
    st.session_state["nav_mode"] = "dashboard"

# ==========================================
# 6. モダンナビゲーション（セグメントコントロール）
# ==========================================
nav_option = st.segmented_control(
    "ナビゲーション",
    ["📊 品質ダッシュボード", "⚙️ データ管理"],
    selection_mode="single",
    default="📊 品質ダッシュボード" if st.session_state.nav_mode == "dashboard" else "⚙️ データ管理",
    label_visibility="collapsed"
)

if nav_option == "📊 品質ダッシュボード" and st.session_state.nav_mode != "dashboard":
    st.session_state.nav_mode = "dashboard"
    st.rerun()
elif nav_option == "⚙️ データ管理" and st.session_state.nav_mode != "management":
    st.session_state.nav_mode = "management"
    st.rerun()

st.divider()

# ==========================================
# 7. 画面描画（モード選択に応じた表示）
# ==========================================
if st.session_state.nav_mode == "dashboard":
    # 📊 品質ダッシュボード: AI登録 + 分析ダッシュボード一体
    tab1_ai_register.render(global_df)
    st.markdown("<br>", unsafe_allow_html=True)
    tab3_dashboard.render(global_df)
elif st.session_state.nav_mode == "management":
    # ⚙️ データ管理: 手動修正 + 管理画面
    mgmt_tab1, mgmt_tab2 = st.tabs(["✍️ 手動修正", "📋 全件管理"])
    with mgmt_tab1:
        tab2_manual.render()
    with mgmt_tab2:
        tab4_management.render(global_df)