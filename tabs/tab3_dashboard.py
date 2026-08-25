"""Tab 3: 分析ダッシュボード（連動絞り込み・品質指標・アラート・AI考察・レポート出力）。"""

import base64
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from config import (
    GENERIC_ERROR_MESSAGE, PERIOD_LIST, PERIOD_MAP, SCORE_OPTIMAL, esc, log_error,
)
import ai_service

# 外部AIへ送信してよいカラム（伝票番号などの識別情報は含めない）
AI_SAFE_COLUMNS = [
    "completion_date", "sheet_type", "restoration_type", "material",
    "contact", "bite", "fit", "comments",
]

# 念のため、AI送信・レポート出力から必ず除外する識別情報カラム
PII_COLUMNS = ["slip_number"]

# 絞り込み条件のセッションキー → 対象カラム
FILTER_KEYS = {
    "s_c": "clinic_name",
    "s_st": "sheet_type",
    "s_m": "material",
    "s_r": "restoration_type",
}

# 品質偏差アラートのしきい値（適正値 3.0 からの許容幅）
ALERT_HIGH = 3.4
ALERT_LOW = 2.6

# スコア別の配色（高級感ある5色パレット）
SCORE_COLORS = {
    "1": "#334155",  # ダークスレート（極端にゆるい・低い）
    "2": "#6366F1",  # スレートインディゴ（ややゆるい・低い）
    "3": "#059669",  # ディープエメラルド（適正基準・良好）
    "4": "#E11D48",  # ローズコーラル（ややきつい・高い）
    "5": "#9F1239"   # クリムゾンワイン（極端にきつい・高い）
}
SCORE_NAME_MAP = {"contact": "コンタクト", "bite": "バイト", "fit": "適合"}


# ==========================================
# 絞り込み
# ==========================================
def _apply_period(frame, period):
    if period == "すべて":
        return frame
    cutoff = pd.Timestamp.today().date() - pd.DateOffset(months=PERIOD_MAP[period])
    return frame[frame["completion_date"] >= cutoff.date()]


def get_dynamic_options(df, col_name):
    """他の絞り込み条件を適用した上で、該当0件の選択肢を除いた候補を返す。"""
    temp = _apply_period(df.copy(), st.session_state.s_p)
    for key, col in FILTER_KEYS.items():
        val = st.session_state[key]
        if val != "すべて" and col_name != col and col in temp.columns:
            temp = temp[temp[col] == val]

    if col_name in temp.columns:
        return ["すべて"] + sorted(list(temp[col_name].dropna().unique()))
    return ["すべて"]


def _filter_dataframe(df):
    f_df = df.copy()
    for key, col in FILTER_KEYS.items():
        val = st.session_state[key]
        if val != "すべて" and col in f_df.columns:
            f_df = f_df[f_df[col] == val]
    return _apply_period(f_df, st.session_state.s_p)


def _render_filters(df):
    st.caption("💡 いずれかの条件を選ぶと、該当しない選択肢が自動で消えます（連動絞り込み）")

    with st.container(border=True):
        cf1, cf2, cf3, cf4, cf5 = st.columns(5)
        opt_c = get_dynamic_options(df, "clinic_name")
        opt_st = get_dynamic_options(df, "sheet_type")
        opt_m = get_dynamic_options(df, "material")
        opt_r = get_dynamic_options(df, "restoration_type")

        idx_p = PERIOD_LIST.index(st.session_state.s_p) if st.session_state.s_p in PERIOD_LIST else 0
        idx_c = opt_c.index(st.session_state.s_c) if st.session_state.s_c in opt_c else 0
        idx_st = opt_st.index(st.session_state.s_st) if st.session_state.s_st in opt_st else 0
        idx_m = opt_m.index(st.session_state.s_m) if st.session_state.s_m in opt_m else 0
        idx_r = opt_r.index(st.session_state.s_r) if st.session_state.s_r in opt_r else 0

        with cf1:
            st.selectbox("医院", opt_c, index=idx_c, key="s_c", label_visibility="collapsed")
        with cf2:
            st.selectbox("シート", opt_st, index=idx_st, key="s_st", label_visibility="collapsed")
        with cf3:
            st.selectbox("期間", PERIOD_LIST, index=idx_p, key="s_p", label_visibility="collapsed")
        with cf4:
            st.selectbox("材料", opt_m, index=idx_m, key="s_m", label_visibility="collapsed")
        with cf5:
            st.selectbox("種別", opt_r, index=idx_r, key="s_r", label_visibility="collapsed")


# ==========================================
# 品質統計関数
# ==========================================
def get_score_distribution(f_df, col):
    """スコア別の件数分布を返す。"""
    if len(f_df) == 0:
        return {i: 0 for i in [1, 2, 3, 4, 5]}
    return f_df[col].value_counts().reindex([1, 2, 3, 4, 5], fill_value=0).to_dict()


def _render_donut_charts(f_df):
    """5色対応ドーナツグラフ（3つ横並び）"""
    if len(f_df) == 0:
        st.info("表示するデータがありません。")
        return

    col1, col2, col3 = st.columns(3)

    for col_idx, (score_col, label) in enumerate([("contact", "コンタクト"),
                                                    ("bite", "バイト"),
                                                    ("fit", "適合")]):
        dist = get_score_distribution(f_df, score_col)
        optimal_count = dist.get(SCORE_OPTIMAL, 0)
        optimal_pct = (optimal_count / len(f_df) * 100) if len(f_df) > 0 else 0

        labels = [f"{i}" for i in [1, 2, 3, 4, 5]]
        values = [dist.get(i, 0) for i in [1, 2, 3, 4, 5]]
        colors = [SCORE_COLORS.get(str(i), "#999") for i in [1, 2, 3, 4, 5]]

        fig = px.pie(
            names=labels, values=values, hole=0.6,
            color_discrete_sequence=colors,
            title=f"{label}<br><span style='font-size:10px'>{'適正率 ' + f'{optimal_pct:.1f}%' if optimal_pct > 0 else 'データなし'}</span>"
        )
        fig.update_traces(
            marker=dict(line=dict(color="#FFFFFF", width=2)),
            textposition="inside",
            textinfo="label+value",
            hovertemplate="<b>スコア %{label}</b><br>件数: %{value}<extra></extra>"
        )
        fig.update_layout(
            showlegend=False,
            dragmode=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=60, b=0, l=0, r=0),
            font=dict(size=12, color="#F9FAFB"),
        )

        # 中心に適正スコア割合を表示
        fig.add_annotation(
            text=f"<b>{optimal_pct:.0f}%</b><br><span style='font-size:10px'>適正</span>",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=20, color="#10B981")
        )

        cols = [col1, col2, col3]
        with cols[col_idx]:
            with st.container(border=True):
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ==========================================
# クロス集計・品質偏差アラート
# ==========================================
def build_alerts(cross_df):
    """XSS対策：DB由来の医院名・材料名はエスケープしてからHTMLに埋め込む。"""
    alerts = []
    for _, row in cross_df[cross_df["件数"] >= 2].iterrows():
        head = f"⚠️ <b>{esc(row['clinic_name'])}</b> × <b>{esc(row['material'])}</b>"
        if row["バイト平均"] >= ALERT_HIGH:
            alerts.append(f"{head}: バイトが高めの傾向があります（平均: {row['バイト平均']:.2f}）")
        elif row["バイト平均"] <= ALERT_LOW:
            alerts.append(f"{head}: バイトが低めの傾向があります（平均: {row['バイト平均']:.2f}）")
        if row["コンタクト平均"] >= ALERT_HIGH:
            alerts.append(f"{head}: コンタクトがきつい傾向があります（平均: {row['コンタクト平均']:.2f}）")
        elif row["コンタクト平均"] <= ALERT_LOW:
            alerts.append(f"{head}: コンタクトがゆるい傾向があります（平均: {row['コンタクト平均']:.2f}）")
    return alerts


def _render_cross_tab(f_df):
    with st.expander("🔍 医院 × 材料 クロス集計・品質偏差アラート", expanded=False):
        cross_df = f_df.groupby(["clinic_name", "material"]).agg(
            件数=("id", "count"),
            コンタクト平均=("contact", "mean"), バイト平均=("bite", "mean"), 適合平均=("fit", "mean"),
        ).reset_index()

        alerts = build_alerts(cross_df)
        if alerts:
            st.markdown("<b>【自動検知された品質アラート】</b>", unsafe_allow_html=True)
            for alt in alerts:
                st.markdown(f'<div class="alert-card">{alt}</div>', unsafe_allow_html=True)
        else:
            st.success("✅ 特定の医院×材料における顕著な品質偏差（大きなズレ）は検出されませんでした。")

        st.markdown("<br><b>【医院 × 材料別 スコアマトリクス】</b>", unsafe_allow_html=True)
        st.dataframe(
            cross_df.style.format(
                {"コンタクト平均": "{:.2f}", "バイト平均": "{:.2f}", "適合平均": "{:.2f}"}),
            use_container_width=True,
        )


# ==========================================
# AI詳細分析
# ==========================================
def _render_ai_analysis(f_df):
    if not st.button("🤖 AI詳細分析（専門基準による考察）", type="primary", use_container_width=True):
        return
    with st.spinner("AIがデータを分析中..."):
        cols = [c for c in AI_SAFE_COLUMNS if c in f_df.columns and c not in PII_COLUMNS]
        dic = f_df[cols].astype(str).to_dict(orient="records")
        try:
            text = ai_service.analyze_quality_data(
                dic, len(f_df), st.session_state.s_c, st.session_state.s_st,
                st.session_state.s_m, st.session_state.s_r,
            )
            st.info(text if text else "分析を完了できませんでした。")
        except Exception as e:
            log_error("AI分析エラー", e)
            st.error(GENERIC_ERROR_MESSAGE)


# ==========================================
# グラフ
# ==========================================
def _render_score_distribution(f_df):
    with st.container(border=True):
        st.markdown("**📊 スコア分布**")
        if len(f_df) == 0:
            return
        dist_data = [
            {"評価項目": SCORE_NAME_MAP[col], "スコア": str(score), "件数": count,
             "割合": f"<b>{count/len(f_df)*100:.1f}%</b>" if count > 0 else ""}
            for col in ["contact", "bite", "fit"]
            for score, count in f_df[col].value_counts().reindex([1, 2, 3, 4, 5], fill_value=0).items()
        ]
        fig_dist = px.bar(pd.DataFrame(dist_data), x="評価項目", y="件数", color="スコア",
                          color_discrete_map=SCORE_COLORS, barmode="stack", text="割合")
        fig_dist.update_traces(textposition="inside", textfont_size=14, textfont_color="#FFFFFF")
        fig_dist.update_layout(
            dragmode=False,
            xaxis=dict(tickfont=dict(size=14, color="#F9FAFB"), title=""),
            yaxis=dict(title="件数", tickfont=dict(color="#F9FAFB")),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#F9FAFB"),
        )
        st.plotly_chart(fig_dist, use_container_width=True, config={"displayModeBar": False})


def _render_monthly_trend(f_df):
    with st.expander("📈 月別推移（品質トレンド）を開く", expanded=False):
        if len(f_df) == 0:
            return
        trend_df = f_df.assign(
            month=pd.to_datetime(f_df["completion_date"]).dt.to_period("M").astype(str)
        ).groupby("month")[["contact", "bite", "fit"]].mean().reset_index()
        fig_line = px.line(trend_df, x="month", y=["contact", "bite", "fit"], markers=True,
                           range_y=[1, 5], color_discrete_sequence=["#10B981", "#E11D48", "#6366F1"])
        fig_line.add_hline(y=3.0, line_dash="dash", line_color="#475569",
                           annotation_text="適正値 (3.0)", annotation_font_color="#9CA3AF")
        fig_line.update_layout(
            dragmode=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#F9FAFB"),
            xaxis=dict(tickfont=dict(color="#F9FAFB")),
            yaxis=dict(tickfont=dict(color="#F9FAFB")),
        )
        st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})


# ==========================================
# 医院向けHTMLレポート
# ==========================================
def build_html_report(f_df, stats):
    """XSS対策：絞り込み条件（DB由来の医院名・材料名等）はエスケープして埋め込む。"""
    (c_m, c_opt), (b_m, b_opt), (f_m, f_opt) = stats
    clinic = esc(st.session_state.s_c)
    sheet_type = esc(st.session_state.s_st)
    material = esc(st.session_state.s_m)
    return f"""
            <html><head><meta charset="utf-8"><title>品質分析レポート - {clinic}</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif; color: #1D1D1F; background-color: #F5F5F7; padding: 30px; }}
                .no-print {{ display: block; }}
                @media print {{
                    body {{ background-color: #FFFFFF !important; padding: 20px !important; font-size: 11pt !important; margin: 0; }}
                    .no-print {{ display: none !important; }}
                    .report-section {{ page-break-inside: avoid; background-color: #FFFFFF !important; border: 1px solid #DDD !important; margin-bottom: 12px !important; padding: 20px !important; }}
                    .metric-card {{ page-break-inside: avoid; background-color: #FAFAFA !important; border: 1px solid #DDD !important; padding: 12px !important; margin: 8px 0 !important; }}
                    h2 {{ page-break-after: avoid; margin-bottom: 12px !important; font-size: 16pt !important; }}
                    h3 {{ page-break-after: avoid; margin-bottom: 10px !important; font-size: 13pt !important; }}
                    table {{ page-break-inside: avoid; width: 100%; border-collapse: collapse; font-size: 10pt !important; }}
                    th, td {{ border: 1px solid #999 !important; padding: 8px !important; }}
                    a.print-btn {{ display: none !important; }}
                    @page {{ size: A4 portrait; margin: 15mm; }}
                }}
            </style>
            </head>
            <body>
                <h2 style="color: #1D1D1F; border-bottom: 2px solid #E5E5EA; padding-bottom: 10px;">AI品質管理カルテ (大阪センター) - 品質分析レポート</h2>
                <p style="color: #8E8E93; font-weight: 500; margin-bottom: 20px;">医院: {clinic} | 種別: {sheet_type} | 材料: {material} | 出力日: {date.today().isoformat()}</p>

                <div class="report-section" style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; margin-bottom: 20px;">
                    <p style="margin: 0; font-size: 15px; line-height: 1.6;">
                        平素より当ラボの技工物をご愛顧いただき、誠にありがとうございます。<br>
                        先生方からいただいた評価シートのデータを元に、直近の品質傾向と分析レポートを作成いたしました。
                    </p>
                </div>

                <div class="report-section" style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; margin-bottom: 20px;">
                    <h3 style="color: #1D1D1F; margin-top: 0;">📊 総合評価（適正スコア「3」の割合）</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 15px;">
                        <div class="metric-card" style="background-color: #F2F7FF; padding: 15px; border-radius: 12px; border-left: 4px solid #007AFF;">
                            <p style="margin: 0 0 8px 0; font-size: 13px; color: #8E8E93; font-weight: 600;">対象件数</p>
                            <p style="margin: 0; font-size: 28px; color: #007AFF; font-weight: 800;">{len(f_df)}<span style="font-size: 14px; color: #1D1D1F; font-weight: 500;"> 件</span></p>
                        </div>
                        <div class="metric-card" style="background-color: #F2F7FF; padding: 15px; border-radius: 12px; border-left: 4px solid #5AC8FA;">
                            <p style="margin: 0 0 8px 0; font-size: 13px; color: #8E8E93; font-weight: 600;">コンタクト適正率</p>
                            <p style="margin: 0; font-size: 28px; color: #5AC8FA; font-weight: 800;">{c_opt:.1f}%</p>
                            <p style="margin: 5px 0 0 0; font-size: 12px; color: #1D1D1F;">平均点: {c_m:.2f}</p>
                        </div>
                        <div class="metric-card" style="background-color: #F2F7FF; padding: 15px; border-radius: 12px; border-left: 4px solid #34C759;">
                            <p style="margin: 0 0 8px 0; font-size: 13px; color: #8E8E93; font-weight: 600;">バイト適正率</p>
                            <p style="margin: 0; font-size: 28px; color: #34C759; font-weight: 800;">{b_opt:.1f}%</p>
                            <p style="margin: 5px 0 0 0; font-size: 12px; color: #1D1D1F;">平均点: {b_m:.2f}</p>
                        </div>
                        <div class="metric-card" style="background-color: #F2F7FF; padding: 15px; border-radius: 12px; border-left: 4px solid #FF9500;">
                            <p style="margin: 0 0 8px 0; font-size: 13px; color: #8E8E93; font-weight: 600;">適合適正率</p>
                            <p style="margin: 0; font-size: 28px; color: #FF9500; font-weight: 800;">{f_opt:.1f}%</p>
                            <p style="margin: 5px 0 0 0; font-size: 12px; color: #1D1D1F;">平均点: {f_m:.2f}</p>
                        </div>
                    </div>
                </div>

                <div style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; margin-bottom: 20px;">
                    <h3 style="color: #1D1D1F; margin-top: 0;">💡 評価スコアの基準について</h3>
                    <p style="font-size: 14px; color: #8E8E93; margin-bottom: 15px;">
                        当ラボでは、以下の基準で品質を管理・分析しております。理想的な状態（適正）を「3」とし、そこからのズレを数値化することで、より精度の高い補綴物製作に役立てています。
                    </p>
                    <table style="width: 100%; border-collapse: collapse; text-align: center; font-size: 14px;">
                        <tr style="background-color: #F2F2F7;">
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">評価項目</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">1</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">2</th>
                            <th style="padding: 10px; border: 2px solid #007AFF; background-color: #E5F1FF; color: #007AFF;">3 (適正)</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">4</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">5</th>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #E5E5EA; font-weight: bold; background-color: #FAFAFA;">コンタクト</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">弱い（緩い）</td><td style="padding: 10px; border: 1px solid #E5E5EA;">やや弱い</td>
                            <td style="padding: 10px; border-top: 2px solid #007AFF; border-bottom: 2px solid #007AFF; border-left: 2px solid #007AFF; border-right: 2px solid #007AFF; background-color: #E5F1FF; font-weight: bold; color: #007AFF;">適正</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">ややきつい</td><td style="padding: 10px; border: 1px solid #E5E5EA;">きつい</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #E5E5EA; font-weight: bold; background-color: #FAFAFA;">バイト</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">低い</td><td style="padding: 10px; border: 1px solid #E5E5EA;">やや低い</td>
                            <td style="padding: 10px; border-top: 2px solid #007AFF; border-bottom: 2px solid #007AFF; border-left: 2px solid #007AFF; border-right: 2px solid #007AFF; background-color: #E5F1FF; font-weight: bold; color: #007AFF;">適正</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">やや高い</td><td style="padding: 10px; border: 1px solid #E5E5EA;">高い</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #E5E5EA; font-weight: bold; background-color: #FAFAFA;">適合</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">緩い</td><td style="padding: 10px; border: 1px solid #E5E5EA;">やや緩い</td>
                            <td style="padding: 10px; border-top: 2px solid #007AFF; border-bottom: 2px solid #007AFF; border-left: 2px solid #007AFF; border-right: 2px solid #007AFF; background-color: #E5F1FF; font-weight: bold; color: #007AFF;">適正</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">ややきつい</td><td style="padding: 10px; border: 1px solid #E5E5EA;">きつい</td>
                        </tr>
                    </table>
                </div>

                <div class="report-section" style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA;">
                    <h3 style="color: #1D1D1F; margin-top: 0;">📌 今後の品質改善に向けて</h3>
                    <p style="font-size: 15px; line-height: 1.6; color: #333; margin-bottom: 0;">
                        先生からのフィードバックは、当ラボの技術向上において最も重要な指標です。<br>
                        上記のデータに基づき、特に適正値から誤差が見られる項目につきましては、担当技工士および製造部門に共有し、バイト・コンタクトの強さやセメントスペースのパラメータを継続的に見直して参ります。<br><br>
                        引き続き、より良い技工物をご提供できるよう努めてまいりますので、忌憚のないご意見をよろしくお願い申し上げます。
                    </p>
                </div>

                <div class="no-print" style="margin-top: 30px; padding: 20px; background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E5EA; text-align: center;">
                    <button onclick="window.print()" style="padding: 12px 28px; background-color: #34C759; color: white; border: none; border-radius: 8px; font-weight: 600; font-size: 16px; cursor: pointer; margin-right: 12px; transition: background-color 0.2s;">🖨️ 印刷 / PDF保存</button>
                    <a href="javascript:void(0)" onclick="document.body.style.opacity='0.5'; setTimeout(() => document.body.style.opacity='1'; window.print(), 100);" style="display: inline-block; padding: 12px 28px; background-color: #007AFF; color: white; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px; cursor: pointer;">💾 HTMLダウンロード</a>
                </div>
            </body>
            <script>
                document.querySelector('a[href^="javascript:void"]')?.addEventListener('click', function() {{
                    const link = document.createElement('a');
                    const html = document.documentElement.outerHTML;
                    const blob = new Blob([html], {{type: 'text/html;charset=utf-8'}});
                    link.href = URL.createObjectURL(blob);
                    link.download = 'quality_report.html';
                    link.click();
                }});
            </script>
            </html>
            """


def _render_report_link(f_df, stats):
    if len(f_df) == 0:
        return
    html = build_html_report(f_df, stats)
    b64 = base64.b64encode(html.encode("utf-8")).decode()
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📋 医院向けレポート出力", unsafe_allow_html=True)
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                f'<a href="data:text/html;base64,{b64}" download="quality_report.html" target="_blank" style="display: inline-block; width: 100%; padding: 14px 24px; background-color: #007AFF; color: white; text-decoration: none; border-radius: 12px; font-weight: 600; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.3); text-align: center;">📥 HTMLダウンロード</a>',
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                f'<iframe srcdoc="{html.replace(chr(34), "&quot;").replace(chr(10), " ")}" style="display: none;" id="printFrame"></iframe><a href="javascript:void(0)" onclick="const iframe = document.getElementById(\'printFrame\'); if (iframe) {{ iframe.contentWindow.print(); }} else {{ const w = window.open(\'data:text/html;base64,{b64}\', \'_blank\'); w.onload = () => w.print(); }}" style="display: inline-block; width: 100%; padding: 14px 24px; background-color: #34C759; color: white; text-decoration: none; border-radius: 12px; font-weight: 600; box-shadow: 0 4px 12px rgba(52, 199, 89, 0.3); text-align: center; cursor: pointer;">🖨️ 印刷 / PDF保存</a>',
                unsafe_allow_html=True,
            )


# ==========================================
# 次回アクション提案
# ==========================================
def _render_next_actions(f_df):
    """次回改善アクション提案（カード表示）"""
    if len(f_df) == 0:
        return

    contact_avg = f_df["contact"].mean() if "contact" in f_df.columns else 3.0
    bite_avg = f_df["bite"].mean() if "bite" in f_df.columns else 3.0
    fit_avg = f_df["fit"].mean() if "fit" in f_df.columns else 3.0

    actions = []
    if contact_avg < ALERT_LOW:
        actions.append("コンタクトがゆるい傾向 → セメントスペースの調整を確認")
    elif contact_avg > ALERT_HIGH:
        actions.append("コンタクトがきつい傾向 → バイト圧調整・研磨パラメータ見直し")

    if bite_avg < ALERT_LOW:
        actions.append("バイトが低い傾向 → セメント層厚さ・支台歯形状を確認")
    elif bite_avg > ALERT_HIGH:
        actions.append("バイトが高い傾向 → 咬合面の削減・バイト力調整")

    if fit_avg < ALERT_LOW:
        actions.append("適合がゆるい傾向 → マージン部の精度向上・セメント流出対策")
    elif fit_avg > ALERT_HIGH:
        actions.append("適合がきつい傾向 → マージン部のクリアランス調整")

    if not actions:
        st.success("✅ すべての指標が適正範囲内です。現状の製造プロセスを継続してください。")
    else:
        with st.container(border=True):
            st.markdown("### 💡 次回改善アクション")
            for action in actions:
                st.markdown(f"- {action}", unsafe_allow_html=True)


# ==========================================
# エントリーポイント
# ==========================================
def render(global_df):
    st.markdown("### 📊 品質分析ダッシュボード")
    if global_df.empty:
        st.info("保存されたデータはまだありません。")
        return

    df = global_df.copy()

    for k in ["s_c", "s_st", "s_p", "s_m", "s_r"]:
        if k not in st.session_state:
            st.session_state[k] = "すべて"

    _render_filters(df)
    f_df = _filter_dataframe(df)

    st.markdown("<br>", unsafe_allow_html=True)

    # 5色対応ドーナツグラフ（3つ横並び）
    _render_donut_charts(f_df)

    st.markdown("<br>", unsafe_allow_html=True)

    # 次回アクション提案
    _render_next_actions(f_df)

    st.markdown("<br>", unsafe_allow_html=True)

    # 詳細分析ビュー（expander）
    with st.expander("📋 詳細分析を開く", expanded=False):
        st.markdown("#### 医院 × 材料 クロス集計・品質偏差アラート")
        if len(f_df) > 0 and "material" in f_df.columns:
            _render_cross_tab(f_df)
        else:
            st.info("クロス集計データがありません。")

        st.markdown("#### スコア分布")
        _render_score_distribution(f_df)

        st.markdown("#### 品質トレンド")
        _render_monthly_trend(f_df)

        st.markdown("#### AI詳細分析")
        _render_ai_analysis(f_df)

    st.markdown("<br>", unsafe_allow_html=True)

    # レポート出力
    if len(f_df) > 0:
        contact_avg = f_df["contact"].mean()
        bite_avg = f_df["bite"].mean()
        fit_avg = f_df["fit"].mean()
        stats = (
            (contact_avg, (f_df["contact"] == SCORE_OPTIMAL).sum() / len(f_df) * 100),
            (bite_avg, (f_df["bite"] == SCORE_OPTIMAL).sum() / len(f_df) * 100),
            (fit_avg, (f_df["fit"] == SCORE_OPTIMAL).sum() / len(f_df) * 100),
        )
        _render_report_link(f_df, stats)
