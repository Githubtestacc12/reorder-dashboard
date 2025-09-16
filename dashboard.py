import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
from datetime import datetime, timedelta

# ------------------------------------------------------
# Page setup
# ------------------------------------------------------
st.set_page_config(page_title="Reorder Report Dashboard", layout="wide")

# ------------------------------------------------------
# Load data
# ------------------------------------------------------
@st.cache_data
def load_data(path: Path):
    return pd.read_excel(path)

report_path = Path("reorder_report.xlsx")
if not report_path.exists():
    st.error(f"❌ Could not find {report_path.resolve()}.\n"
             f"Run reorder_alerts.py first.")
    st.stop()

df = load_data(report_path)

# ------------------------------------------------------
# Add Suggested Reorder Date
# ------------------------------------------------------
def add_suggested_date(data: pd.DataFrame, buffer_days: int = 5) -> pd.DataFrame:
    if "Days Until Out" not in data.columns:
        return data
    df_copy = data.copy()

    # Round Days Until Out to nearest whole number
    days_rounded = df_copy["Days Until Out"].round().fillna(0).astype(int)

    base_date = pd.to_datetime(datetime.now().date())
    df_copy["Suggested Reorder Date"] = base_date + pd.to_timedelta(
        days_rounded - buffer_days, unit="D"
    )

    # Clip to today if result is in the past
    today = pd.to_datetime(datetime.now().date())
    df_copy.loc[df_copy["Suggested Reorder Date"] < today, "Suggested Reorder Date"] = today

    # Keep only the date (no time)
    df_copy["Suggested Reorder Date"] = df_copy["Suggested Reorder Date"].dt.date

    return df_copy

df = add_suggested_date(df, buffer_days=5)

# ------------------------------------------------------
# Title & info
# ------------------------------------------------------
st.title("📊 Reorder Report Dashboard")
st.caption(f"Last updated: {datetime.now():%Y-%m-%d}")

# ------------------------------------------------------
# Sidebar filters
# ------------------------------------------------------
st.sidebar.header("Filters")

cust_values = sorted(df["Customer"].fillna("(Blank)").unique())
sel_all_cust = st.sidebar.checkbox("Select All Customers", value=True)
customers = cust_values if sel_all_cust else st.sidebar.multiselect("Customer", cust_values, default=[])
mask_customer = df["Customer"].fillna("(Blank)").isin(customers)

item_col = "Item" if "Item" in df.columns else "Item #"
available_items = df.loc[mask_customer, item_col].fillna("(Blank)").unique()
item_values_str = sorted([str(v) for v in available_items])
sel_all_items = st.sidebar.checkbox("Select All Items", value=True)
items = item_values_str if sel_all_items else st.sidebar.multiselect("Item", item_values_str, default=[])
mask_item = df[item_col].fillna("(Blank)").astype(str).isin(items)

status_choice = st.sidebar.radio(
    "Show rows with status:",
    options=["All", "Reorder Soon", "OK"],
    index=0
)
mask_status = True if status_choice == "All" else df["Status"].fillna("(Blank)") == status_choice

max_days = int(df["Days Until Out"].max(skipna=True))
days_slider = st.sidebar.slider("Max Days Until Out", 0, max_days, max_days)
mask_days = (df["Days Until Out"] <= days_slider) | df["Days Until Out"].isna()

if "Last Due" in df.columns:
    min_date, max_date = df["Last Due"].min(), df["Last Due"].max()
    date_range = st.sidebar.date_input("Last Due Range", [min_date, max_date])
    if isinstance(date_range, list) and len(date_range) == 2:
        start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        mask_date = df["Last Due"].between(start_date, end_date) | df["Last Due"].isna()
    else:
        mask_date = True
else:
    mask_date = True

query = st.sidebar.text_input("🔎 Search (any text)")
mask_search = (
    df.astype(str).apply(lambda r: r.str.contains(query, case=False, na=False), axis=1)
    if query else True
)

show_bar = st.sidebar.checkbox("Show bar chart: Suggested Order Qty by Customer", value=True)

# ------------------------------------------------------
# Apply all masks
# ------------------------------------------------------
filtered = df[
    mask_customer
    & mask_status
    & mask_item
    & mask_days
    & mask_date
    & mask_search
]

# ------------------------------------------------------
# KPI cards (rounded)
# ------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
if not filtered.empty:
    total_items = int(len(filtered))
    need_reorder = int((filtered["Status"] == "Reorder Soon").sum())
    avg_days = int(round(filtered["Days Until Out"].mean(skipna=True))) if not filtered["Days Until Out"].dropna().empty else 0
    total_qty = int(round(filtered["Suggested Order Qty"].sum(skipna=True)))
else:
    total_items = need_reorder = total_qty = 0
    avg_days = 0

col1.metric("Total Items", total_items)
col2.metric("Need Reorder", need_reorder)
col3.metric("Avg Days Until Out", avg_days)
col4.metric("Total Suggested Qty", total_qty)

# ------------------------------------------------------
# Detailed Records
# ------------------------------------------------------
def highlight_status(row):
    if row["Status"] == "Reorder Soon":
        return ["background-color: #fff9e6; color:black;"] * len(row)
    return ["" for _ in row]

st.subheader("Detailed Records")
if not filtered.empty:
    cols = filtered.columns.tolist()
    if "Days Until Out" in cols and "Suggested Reorder Date" in cols:
        cols.insert(cols.index("Days Until Out") + 1, cols.pop(cols.index("Suggested Reorder Date")))
    st.dataframe(filtered[cols].style.apply(highlight_status, axis=1), use_container_width=True)
else:
    st.info("No rows to display with current filters.")

# ------------------------------------------------------
# Charts
# ------------------------------------------------------
if not filtered.empty:
    if show_bar:
        fig_bar = px.bar(
            filtered,
            x="Customer",
            y="Suggested Order Qty",
            color="Status",
            text_auto=True,
            title="Suggested Order Quantity by Customer",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    fig_pie = px.pie(
        filtered,
        names="Status",
        title="Status Share",
        hole=0.35,
    )
    st.plotly_chart(fig_pie, use_container_width=True)

    if "Last Due" in filtered.columns and pd.api.types.is_datetime64_any_dtype(filtered["Last Due"]):
        trend = (
            filtered.assign(month=filtered["Last Due"].dt.to_period("M"))
            .groupby("month")["Status"]
            .apply(lambda x: (x == "Reorder Soon").sum())
            .reset_index(name="Items Needing Reorder")
        )
        if not trend.empty:
            trend["month"] = trend["month"].dt.to_timestamp()
            st.line_chart(trend.set_index("month"))
else:
    st.warning("⚠️ No data matches the selected filters.")

# ------------------------------------------------------
# Download filtered data
# ------------------------------------------------------
csv_bytes = filtered.to_csv(index=False).encode()
st.download_button(
    "💾 Download filtered data as CSV",
    csv_bytes,
    file_name="filtered_reorder_report.csv",
    mime="text/csv",
)

# ------------------------------------------------------
# File upload
# ------------------------------------------------------
uploaded = st.file_uploader("Upload a new reorder report", type=["xlsx"])
if uploaded:
    new_df = pd.read_excel(uploaded)
    st.success("✅ New report loaded below:")
    st.dataframe(new_df, use_container_width=True)
