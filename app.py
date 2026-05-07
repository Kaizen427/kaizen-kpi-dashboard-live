import streamlit as st
import requests
import pandas as pd
from collections import defaultdict
from datetime import datetime

st.set_page_config(page_title="Kaizen KPI Dashboard (Live)", layout="wide", page_icon="📊")

st.markdown("""
<style>
  .main { background-color: #F8FAFC; }
  .metric-card {
    background: white;
    border-radius: 12px;
    padding: 20px 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    border-left: 4px solid #6366F1;
    margin-bottom: 12px;
  }
  .metric-label { font-size: 13px; color: #64748B; font-weight: 500; margin-bottom: 4px; }
  .metric-value { font-size: 26px; font-weight: 700; color: #1E293B; }
  .metric-sub   { font-size: 12px; color: #94A3B8; margin-top: 2px; }
  .section-title {
    font-size: 15px; font-weight: 700; color: #1E293B;
    text-transform: uppercase; letter-spacing: 0.05em;
    margin: 24px 0 12px 0;
  }
  .funnel-bar {
    background: #EEF2FF; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 8px;
    display: flex; justify-content: space-between; align-items: center;
  }
</style>
""", unsafe_allow_html=True)

API_URL   = "https://api-p.lbkwork.com/admin-luke-manager/luke/businessDataStat/channelBoard"
MIN_MONTH = "2026-03"   # Only show March 2026 onwards


# ── Auth: try Lark app credentials → TWALK_TOKEN secret → manual input ───────

def get_lark_tenant_token() -> str | None:
    """Get a tenant_access_token using LARK_APP_ID + LARK_APP_SECRET."""
    app_id     = st.secrets.get("LARK_APP_ID", "")
    app_secret = st.secrets.get("LARK_APP_SECRET", "")
    if not app_id or not app_secret:
        return None
    try:
        resp = requests.post(
            "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        data = resp.json()
        return data.get("tenant_access_token") or None
    except Exception:
        return None

def token_works(token: str) -> bool:
    """Quick probe to verify a token is accepted by the Twalk API."""
    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "origin": "https://twalk-p.lbkwork.com",
                "referer": "https://twalk-p.lbkwork.com/",
                "ex-language": "en-US",
                "ex-station": "1",
            },
            json={"pageNo": 1, "dateLabel": 3, "pageNum": 1, "pageSize": 1},
            timeout=15,
        )
        return resp.status_code == 200 and resp.json().get("code") == 200
    except Exception:
        return False

@st.cache_data(ttl=3300, show_spinner=False)  # re-fetch Lark token every ~55 min
def resolve_bearer_token() -> tuple[str, str]:
    """
    Returns (token, source) where source is one of:
      'lark'   – obtained automatically via Lark app credentials
      'secret' – read from TWALK_TOKEN secret
      ''       – not found (manual input required)
    """
    # 1. Try Lark app credentials (same ones used by the existing dashboard)
    lark_token = get_lark_tenant_token()
    if lark_token and token_works(lark_token):
        return lark_token, "lark"

    # 2. Fall back to manually-stored TWALK_TOKEN
    stored = st.secrets.get("TWALK_TOKEN", "")
    if stored and token_works(stored):
        return stored, "secret"

    return "", ""


# ── Fetch all data pages ─────────────────────────────────────────────────────

def parse_num(val) -> float:
    try:
        return float(str(val).replace(",", "").replace(" ", ""))
    except Exception:
        return 0.0

@st.cache_data(ttl=300, show_spinner="Fetching data from Twalk...")
def load_data(bearer_token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "accept": "application/json, text/plain, */*",
        "origin": "https://twalk-p.lbkwork.com",
        "referer": "https://twalk-p.lbkwork.com/",
        "ex-language": "en-US",
        "ex-station": "1",
    }
    all_records = []
    page = 1
    while True:
        payload = {"pageNo": page, "dateLabel": 3, "pageNum": page, "pageSize": 50}
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 401:
            return []   # signal expired token
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 200:
            return []
        data = body["data"]
        for row in data["resultList"]:
            mk = row.get("bizDate", "")
            if mk < MIN_MONTH:          # skip anything before March 2026
                continue
            all_records.append({
                "bd":          row.get("channelName", ""),
                "region":      row.get("channelAdmin", ""),
                "director":    row.get("allChannelAdmin", ""),
                "month_key":   mk,
                "reg":         int(row.get("registerUserCnt", 0) or 0),
                "ftd":         int(row.get("firstRechargeUserCnt", 0) or 0),
                "ftt":         int(row.get("firstTradeUserCnt", 0) or 0),
                "efttc":       int(row.get("efttcUserCnt", 0) or 0),
                "dep":         int(row.get("depositUserCnt", 0) or 0),
                "net_dep":     parse_num(row.get("netRechargeAmt", 0)),
                "contract_tv": parse_num(row.get("futuresTradeAmt", 0)),
                "spot_tv":     parse_num(row.get("spotTradeAmt", 0)),
                "net_fees":    parse_num(row.get("profitFee", 0)),
            })
        if not data.get("hasNext", False):
            break
        page += 1
    return all_records


def fmt_num(v, prefix="", suffix=""):
    if v >= 1_000_000: return f"{prefix}{v/1_000_000:.2f}M{suffix}"
    if v >= 1_000:     return f"{prefix}{v/1_000:.1f}K{suffix}"
    return f"{prefix}{v:,.0f}{suffix}"

def metric_card(label, value, sub=""):
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{value}</div>
      {'<div class="metric-sub">'+sub+'</div>' if sub else ''}
    </div>""", unsafe_allow_html=True)

def month_label(ym: str) -> str:
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%B %Y")
    except Exception:
        return ym


# ── Resolve token (auto, no user interaction needed if credentials present) ──
with st.spinner("Connecting to Twalk..."):
    auto_token, token_source = resolve_bearer_token()

bearer_token = auto_token

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 Kaizen")
    st.title("KPI Filters")
    st.markdown("---")

    # Only show token input if auto-auth failed
    if not bearer_token:
        st.markdown("**⚠️ Token needed**")
        manual_token = st.text_input(
            "Bearer Token",
            type="password",
            help="Twalk → DevTools → Network → channelBoard → Authorization header"
        )
        if manual_token:
            bearer_token = manual_token
        else:
            st.warning(
                "No se pudo autenticar automáticamente.\n\n"
                "Pega tu Bearer Token arriba **o** agrega `TWALK_TOKEN` a los Secrets de Streamlit."
            )
        st.markdown("---")

    if not bearer_token:
        st.stop()

    # Load data now (token is ready)
    records = load_data(bearer_token)

    if not records:
        st.cache_data.clear()
        resolve_bearer_token.clear()
        if token_source == "lark":
            st.error("El token Lark expiró. Agrega `TWALK_TOKEN` a los Secrets.")
        else:
            st.error("Token inválido o expirado. Actualiza `TWALK_TOKEN` en Secrets.")
        st.stop()

    all_month_keys = sorted(set(r["month_key"] for r in records if r["month_key"]), reverse=True)
    all_bds        = sorted(set(r["bd"] for r in records if r["bd"]))
    default_months = all_month_keys[:3] if len(all_month_keys) >= 3 else all_month_keys

    sel_bd = st.selectbox("BD Agent", ["All BDs"] + all_bds)

    month_display    = {month_label(k): k for k in all_month_keys}
    sel_month_labels = st.multiselect(
        "Period(s)",
        options=list(month_display.keys()),
        default=[month_label(k) for k in default_months],
        help="Selecciona uno o varios meses",
    )
    sel_months = [month_display[l] for l in sel_month_labels] if sel_month_labels else all_month_keys

    st.markdown("---")
    src_label = {"lark": "🟢 Auto (Lark)", "secret": "🟡 Secret", "": "🔴 Manual"}.get(token_source, "")
    st.caption(f"Auth: {src_label}\nCache: 5 min")
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()


# ── Filter ────────────────────────────────────────────────────────────────────
filtered = [r for r in records if r["month_key"] in sel_months]
if sel_bd != "All BDs":
    filtered = [r for r in filtered if r["bd"] == sel_bd]

def total(key): return sum(r[key] for r in filtered)

reg    = total("reg");         ftd    = total("ftd")
ftt    = total("ftt");         efttc  = total("efttc")
ctr_tv = total("contract_tv"); spt_tv = total("spot_tv")
tot_tv = ctr_tv + spt_tv;     fees   = total("net_fees")


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📊 Kaizen Team — KPI Dashboard")
period_label = " + ".join(sel_month_labels) if sel_month_labels else "All periods"
agent_label  = sel_bd if sel_bd != "All BDs" else "All BDs"
st.markdown(f"**{agent_label}  ·  {period_label}**")
st.markdown("---")


# ── KPI Cards ─────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Cumulative Results</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1: metric_card("Registered Users",          f"{int(reg):,}")
with c2: metric_card("First Time Deposit (FTD)",  f"{int(ftd):,}")
with c3: metric_card("First Time Trade (FTT)",    f"{int(ftt):,}")
with c4: metric_card("EFTTC — Converted Traders", f"{int(efttc):,}")

c5, c6, c7, c8 = st.columns(4)
with c5: metric_card("Contract Trading Vol.",  fmt_num(ctr_tv, "$"))
with c6: metric_card("Spot Trading Vol.",      fmt_num(spt_tv, "$"))
with c7: metric_card("Total Trading Vol.",     fmt_num(tot_tv, "$"))
with c8: metric_card("Net Fees (USD)",         fmt_num(fees,   "$"))


# ── Funnel ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Conversion Funnel</div>', unsafe_allow_html=True)
f1, f2 = st.columns([1, 2])

with f1:
    reg2ftd   = ftd   / reg * 100 if reg else 0
    reg2ftt   = ftt   / reg * 100 if reg else 0
    reg2efttc = efttc / reg * 100 if reg else 0
    for lbl, val in [("Reg → FTD", reg2ftd), ("Reg → FTT", reg2ftt), ("Reg → EFTTC", reg2efttc)]:
        st.markdown(f"""
        <div class="funnel-bar">
          <span style="color:#1E293B;font-weight:600">{lbl}</span>
          <span style="color:#6366F1;font-weight:700;font-size:18px">{val:.1f}%</span>
        </div>""", unsafe_allow_html=True)

with f2:
    bd_summary = defaultdict(lambda: defaultdict(float))
    for r in records:
        if r["month_key"] not in sel_months:
            continue
        bd_summary[r["bd"]]["reg"]    += r["reg"]
        bd_summary[r["bd"]]["efttc"]  += r["efttc"]
        bd_summary[r["bd"]]["tot_tv"] += r["contract_tv"] + r["spot_tv"]
        bd_summary[r["bd"]]["fees"]   += r["net_fees"]

    rows_df = []
    for bd, m in sorted(bd_summary.items(), key=lambda x: -x[1]["tot_tv"]):
        if bd and (sel_bd == "All BDs" or bd == sel_bd):
            rows_df.append({
                "BD Agent": bd,
                "Reg":      int(m["reg"]),
                "EFTTC":    int(m["efttc"]),
                "Total TV": fmt_num(m["tot_tv"], "$"),
                "Net Fees": fmt_num(m["fees"],   "$"),
            })
    if rows_df:
        st.dataframe(pd.DataFrame(rows_df), use_container_width=True, hide_index=True)


# ── Month-by-month breakdown (only when multiple months selected) ─────────────
if len(sel_months) > 1:
    st.markdown('<div class="section-title">Month-by-Month Breakdown</div>', unsafe_allow_html=True)
    month_rows = []
    for mk in sorted(sel_months):
        mdata = [r for r in records if r["month_key"] == mk]
        if sel_bd != "All BDs":
            mdata = [r for r in mdata if r["bd"] == sel_bd]
        if not mdata:
            continue
        month_rows.append({
            "Month":    month_label(mk),
            "Reg":      sum(r["reg"]   for r in mdata),
            "FTD":      sum(r["ftd"]   for r in mdata),
            "FTT":      sum(r["ftt"]   for r in mdata),
            "EFTTC":    sum(r["efttc"] for r in mdata),
            "Total TV": fmt_num(sum(r["contract_tv"] + r["spot_tv"] for r in mdata), "$"),
            "Net Fees": fmt_num(sum(r["net_fees"]    for r in mdata), "$"),
        })
    if month_rows:
        st.dataframe(pd.DataFrame(month_rows), use_container_width=True, hide_index=True)


st.markdown("---")
st.caption("📡 Data source: Twalk API (live)  ·  Kaizen Team")
