"""定数定義・テーマ設定・CSSスタイル。

このモジュールは import 時点で streamlit を読み込みません。
app.py が `import streamlit` より前に setup_theme() を呼び出せるようにするためです
（テーマ設定ファイル .streamlit/config.toml を先に生成する必要があるため）。
"""

import html
import logging
import os
import re

# ==========================================
# 選択肢マスタ
# ==========================================
SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "PEEK", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]

# 評価スコアの定義（3が適正、1が弱い/低い、5がきつい/高い）
SCORE_MIN = 1
SCORE_MAX = 5
SCORE_OPTIMAL = 3

# 期間フィルタの選択肢とヶ月数の対応
PERIOD_LIST = ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"]
PERIOD_MAP = {"直近1ヶ月": 1, "直近2ヶ月": 2, "直近3ヶ月": 3, "直近6ヶ月": 6}

# ==========================================
# セキュリティ設定
# ==========================================
# アップロード可能なファイルサイズの上限
MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# 画面に表示する汎用エラーメッセージ（例外の詳細は画面に出さずログへ出力する）
GENERIC_ERROR_MESSAGE = "⚠️ 処理中にエラーが発生しました。時間をおいて再度お試しください。"


# ==========================================
# 個人情報保護 ①：ログインロール
# ==========================================
# ★ 患者名（patient_name）はシステム全体で一切取得・保存・表示しない。
#    AIにも読み取らせないため、伏せ字（マスク）処理そのものを廃止している。
#    レコードの識別には伝票番号（slip_number）を使用すること。

# 管理者アカウント（secrets.toml の [passwords] のID）
ADMIN_USERNAMES = {"admin"}


def _session_get(key, default=None):
    """streamlit の session_state から安全に値を取り出す。

    このモジュールは app.py が `import streamlit` する前に読み込まれるため、
    モジュールレベルでは streamlit を import しない（冒頭のドキュメント参照）。
    セッションを参照できない場合は default を返し、常に安全側（マスク）へ倒す。
    """
    try:
        import streamlit as st

        return st.session_state.get(key, default)
    except Exception:
        return default


def get_current_user():
    """認証済みのログインIDを返す（未認証なら空文字）。"""
    if not _session_get("password_correct", False):
        return ""
    return str(_session_get("current_user", "") or "")


def is_admin():
    """管理者アカウントかどうか。"""
    return get_current_user() in ADMIN_USERNAMES


# ==========================================
# 個人情報保護 ②：機密データのログ出力遮断
# ==========================================
# ログ/標準出力に現れた場合に値を伏せるキー（例外メッセージ内のJSONやdictも対象）
# ※ patient_name はシステムでは扱わないが、旧データ・外部入力（CSV等）由来の値が
#    ログへ紛れ込む可能性に備えて、伏せ字対象として残している。
SENSITIVE_KEYS = (
    "patient_name", "patient", "slip_number", "slip", "phone", "phone_number",
    "tel", "telephone", "mobile", "fax", "email", "mail", "address",
    "患者名", "患者", "氏名", "伝票番号", "伝票", "電話番号", "電話", "住所", "メールアドレス",
)

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PATTERN = "|".join(
    re.escape(k) for k in sorted(SENSITIVE_KEYS, key=len, reverse=True)
)

_REDACTION_RULES = (
    # "patient_name": "田中 太郎" / 'slip_number': '12345' のようなクオート付きの値
    (
        re.compile(
            rf'(?<![A-Za-z0-9_])(["\']?(?:{_SENSITIVE_KEY_PATTERN})["\']?\s*[:=]\s*)'
            rf'(["\'])(?:\\.|(?!\2).)*\2',
            re.IGNORECASE,
        ),
        rf'\g<1>"{REDACTED}"',
    ),
    # patient_name=田中太郎 / 患者名: 田中太郎 のようなクオート無しの値
    # （置換済みの値を二重に処理しないよう先読みで除外する）
    (
        re.compile(
            rf'(?<![A-Za-z0-9_])((?:{_SENSITIVE_KEY_PATTERN})\s*[:=]\s*)'
            rf'(?!["\']?\[REDACTED\])[^\s,;)}}\]&]+',
            re.IGNORECASE,
        ),
        rf'\g<1>{REDACTED}',
    ),
    # 電話番号（0始まり／+81始まり、ハイフン・スペース区切りの有無を問わない）
    (
        re.compile(r'(?<![0-9])(?:\+81[-\s]?\d{1,4}|0\d{1,4})[-\s]?\d{1,4}[-\s]?\d{3,4}(?![0-9])'),
        REDACTED,
    ),
)


def redact_pii(text):
    """患者氏名・電話番号・伝票番号などの個人識別情報を伏せ字へ置換する。

    ログ出力・標準出力に個人情報を平文で残さないためのフィルタ。
    """
    if text is None:
        return text
    out = str(text)
    for pattern, replacement in _REDACTION_RULES:
        out = pattern.sub(replacement, out)
    return out


class PIIRedactingFormatter(logging.Formatter):
    """整形後のログ全文（例外トレースバックを含む）から個人識別情報を除去する。"""

    def format(self, record):
        return redact_pii(super().format(record))


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# ルートハンドラ経由の出力（Streamlit本体・supabase・httpx等のログを含む）を全てフィルタする
for _handler in logging.getLogger().handlers:
    _handler.setFormatter(PIIRedactingFormatter(LOG_FORMAT))

logger = logging.getLogger("ai_quality_karte")


def safe_print(*values, **kwargs):
    """print() の代替。個人識別情報を伏せ字にしてから標準出力へ書き出す。

    デバッグ目的でも生の print() は使わず、必ずこの関数を経由すること。
    """
    print(*(redact_pii(v) for v in values), **kwargs)


# ==========================================
# ★ Inspora/Linear風ダークテーマの自動設定
# ==========================================
def setup_theme():
    os.makedirs(".streamlit", exist_ok=True)
    theme_file = ".streamlit/config.toml"
    if not os.path.exists(theme_file):
        with open(theme_file, "w") as f:
            f.write("""
[theme]
primaryColor = "#10B981"
backgroundColor = "#090D16"
secondaryBackgroundColor = "#111827"
textColor = "#F9FAFB"
font = "sans serif"

[client]
showErrorDetails = false

[logger]
level = "warning"
""")
        return True
    return False


# ==========================================
# カスタムCSS（Inspora/Linear風ダークテーマ）
# ==========================================
CUSTOM_CSS = """
<style>
    .stApp {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif !important;
        background-color: #090D16;
        color: #F9FAFB;
    }
    body { background-color: #090D16 !important; }
    #MainMenu, header, footer { visibility: hidden; }

    .custom-title {
        font-size: clamp(1.8rem, 5vw, 2.4rem);
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #F9FAFB;
        margin-bottom: 20px;
    }

    .stButton>button {
        border-radius: 8px !important;
        font-weight: 500 !important;
        font-size: 14px !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
    }

    .stButton>button[kind="primary"] {
        background-color: #10B981 !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.15) !important;
    }

    .stButton>button[kind="primary"]:hover {
        background-color: #059669 !important;
        box-shadow: 0 6px 16px rgba(16, 185, 129, 0.25) !important;
    }

    .stButton>button[kind="secondary"] {
        background-color: transparent !important;
        color: #9CA3AF !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
    }

    .stButton>button[kind="secondary"]:hover {
        background-color: rgba(255, 255, 255, 0.05) !important;
        color: #F9FAFB !important;
    }

    /* Container 스타일 */
    [data-testid="stVerticalBlock"] > div[data-testid="stContainer"],
    [data-testid="stVerticalBlock"] > div[style*="border"] {
        background-color: #111827 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
        padding: 20px !important;
        box-shadow: none !important;
    }

    /* Expander 스타일 */
    .streamlit-expanderHeader {
        background-color: #1F2937 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        color: #F9FAFB !important;
    }

    .streamlit-expanderHeader:hover {
        background-color: #2D3748 !important;
    }

    /* 입력 필드 */
    input, select, textarea {
        background-color: #1F2937 !important;
        color: #F9FAFB !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        padding: 8px 12px !important;
        transition: all 0.2s ease !important;
    }

    input:focus, select:focus, textarea:focus {
        border-color: #10B981 !important;
        box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1) !important;
    }

    /* 메트릭 카드 */
    .metric-card {
        background: rgba(17, 24, 39, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 20px;
        border-radius: 12px;
        text-align: center;
        box-shadow: none;
    }

    .metric-card h2 {
        font-weight: 700;
        letter-spacing: -0.01em;
        color: #F9FAFB;
    }

    /* 알림 카드 */
    .alert-card {
        padding: 14px 18px;
        border-left: 4px solid #10B981;
        background-color: rgba(16, 185, 129, 0.08);
        border-radius: 8px;
        margin-bottom: 10px;
        color: #F9FAFB;
        font-weight: 500;
    }

    /* Divider */
    hr { border-color: rgba(255, 255, 255, 0.08) !important; }

    /* 테이블 */
    [data-testid="stDataFrame"] {
        background-color: #111827 !important;
    }

    .stDataFrame > table { background-color: #111827 !important; }

    /* セグメントコントロール */
    [data-testid="stSegmentedControl"] button {
        background-color: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #9CA3AF !important;
    }

    [data-testid="stSegmentedControl"] button[aria-selected="true"] {
        background-color: #10B981 !important;
        color: #FFFFFF !important;
        border-color: #10B981 !important;
    }

    /* Info/Success/Error メッセージ */
    [data-testid="stAlert"] {
        background-color: rgba(16, 185, 129, 0.1) !important;
        border-color: rgba(16, 185, 129, 0.3) !important;
    }
</style>
"""


# ==========================================
# 共通ヘルパー
# ==========================================
def safe_int(val, default=SCORE_OPTIMAL):
    """評価スコアを 1〜5 の範囲に丸める。変換できない場合は default を返す。"""
    try:
        return max(SCORE_MIN, min(SCORE_MAX, int(float(val))))
    except (ValueError, TypeError):
        return default


def esc(val):
    """XSS対策：HTMLへ埋め込む前に文字列をエスケープする。

    unsafe_allow_html=True の st.markdown や、生成するHTMLレポートに
    ユーザー入力・DB由来の値を埋め込む箇所では必ずこの関数を通すこと。
    """
    if val is None:
        return ""
    return html.escape(str(val), quote=True)


def log_error(context, exc):
    """例外の詳細をターミナル/ログにのみ出力する（画面には表示しない）。

    メッセージ・例外文言はここで、トレースバックは PIIRedactingFormatter 側で
    それぞれ個人識別情報を伏せ字化する（二重に遮断する）。
    """
    logger.error("%s: %s", redact_pii(context), redact_pii(exc), exc_info=True)


def is_oversized(file_obj):
    """アップロードファイルが上限サイズを超えていれば True。"""
    if not file_obj:
        return False
    size = getattr(file_obj, "size", None)
    if size is None:
        try:
            size = len(file_obj.getvalue())
        except Exception:
            return False
    return size > MAX_UPLOAD_SIZE_BYTES


def oversized_files(file_objs):
    """上限サイズを超えたファイル名の一覧を返す。"""
    return [getattr(f, "name", "不明なファイル") for f in (file_objs or []) if is_oversized(f)]
