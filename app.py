"""
Brand Traders – Sales Analytics Dashboard (Streamlit)

Run:
    pip install streamlit pandas plotly
    streamlit run app.py

Place the 7 CSV files in a folder called ./data (next to this file) or in the
same folder as app.py. If they are not found, the sidebar lets you upload them.
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Brand Traders – Sales Analytics", page_icon="📊", layout="wide")

TABLES = ["categories", "customers", "employees", "order_details", "orders", "products", "shippers"]
HERE = Path(__file__).parent
MAP_FIX = {"USA": "United States", "UK": "United Kingdom"}


# ----------------------------------------------------------------------------
# Loading & joining
# ----------------------------------------------------------------------------
def read_csv_any(src) -> pd.DataFrame:
    """Read a CSV from a path or an uploaded file, trying common encodings."""
    last = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            if hasattr(src, "seek"):
                src.seek(0)
            return pd.read_csv(src, encoding=enc)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def find_data_dir():
    for d in (HERE / "data", HERE):
        if all((d / f"{t}.csv").exists() for t in TABLES):
            return d
    return None


@st.cache_data(show_spinner="Loading and joining tables…")
def load_from_dir(path: str) -> dict:
    return {t: read_csv_any(Path(path) / f"{t}.csv") for t in TABLES}


def load_from_uploads(files) -> dict | None:
    by_name = {Path(f.name).stem.lower(): f for f in files}
    if not all(t in by_name for t in TABLES):
        return None
    return {t: read_csv_any(by_name[t]) for t in TABLES}


@st.cache_data(show_spinner="Joining tables…")
def build_sales(raw: dict) -> pd.DataFrame:
    """One row per order line with every dimension joined in."""
    od = raw["order_details"].copy()
    o = raw["orders"].copy()
    p = raw["products"].rename(columns={"unitPrice": "listPrice"})
    c = raw["categories"][["categoryID", "categoryName"]]
    cu = raw["customers"].rename(
        columns={"companyName": "customer", "city": "customerCity", "country": "customerCountry"}
    )
    e = raw["employees"][["employeeID", "employeeName", "title"]].rename(columns={"title": "employeeTitle"})
    s = raw["shippers"].rename(columns={"companyName": "shipper"})

    for col in ("orderDate", "requiredDate", "shippedDate"):
        o[col] = pd.to_datetime(o[col], errors="coerce")

    df = (
        od.merge(o, on="orderID", how="left")
        .merge(p[["productID", "productName", "listPrice", "discontinued", "categoryID"]], on="productID", how="left")
        .merge(c, on="categoryID", how="left")
        .merge(cu[["customerID", "customer", "contactName", "customerCity", "customerCountry"]], on="customerID", how="left")
        .merge(e, on="employeeID", how="left")
        .merge(s, on="shipperID", how="left")
    )
    df["gross"] = df["unitPrice"] * df["quantity"]
    df["discountAmt"] = df["gross"] * df["discount"]
    df["revenue"] = df["gross"] - df["discountAmt"]
    df["month"] = df["orderDate"].dt.to_period("M").dt.to_timestamp()
    df["year"] = df["orderDate"].dt.year
    df["monthNum"] = df["orderDate"].dt.month
    df["weekday"] = df["orderDate"].dt.day_name()
    df["deliveryDays"] = (df["shippedDate"] - df["orderDate"]).dt.days
    # 1.0 = late, 0.0 = on time, NaN = not shipped yet
    df["late"] = (df["shippedDate"] > df["requiredDate"]).astype(float)
    df.loc[df["shippedDate"].isna(), "late"] = float("nan")
    return df


def order_level(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per order (freight is an order-level amount)."""
    return (
        df.groupby("orderID")
        .agg(
            orderDate=("orderDate", "first"),
            month=("month", "first"),
            customer=("customer", "first"),
            customerCountry=("customerCountry", "first"),
            employeeName=("employeeName", "first"),
            shipper=("shipper", "first"),
            freight=("freight", "first"),
            deliveryDays=("deliveryDays", "first"),
            late=("late", "first"),
            shippedDate=("shippedDate", "first"),
            revenue=("revenue", "sum"),
            items=("quantity", "sum"),
            lines=("productID", "count"),
        )
        .reset_index()
    )


def money(x: float) -> str:
    return f"${x:,.0f}"


# ----------------------------------------------------------------------------
# Data source
# ----------------------------------------------------------------------------
st.sidebar.title("📊 Brand Traders")
data_dir = find_data_dir()
raw = None
if data_dir:
    raw = load_from_dir(str(data_dir))
    st.sidebar.caption(f"Data loaded from `{data_dir}`")
else:
    st.sidebar.warning("CSV files not found next to app.py. Upload all 7 files:")
    up = st.sidebar.file_uploader("CSV files", type="csv", accept_multiple_files=True)
    if up:
        raw = load_from_uploads(up)
        if raw is None:
            st.sidebar.error("Missing files. Need: " + ", ".join(f"{t}.csv" for t in TABLES))

if raw is None:
    st.title("Brand Traders – Sales Analytics")
    st.info("Add the 7 CSV files (categories, customers, employees, order_details, orders, products, shippers) to continue.")
    st.stop()

sales_all = build_sales(raw)

# ----------------------------------------------------------------------------
# Filters
# ----------------------------------------------------------------------------
st.sidebar.header("Filters")
dmin, dmax = sales_all["orderDate"].min().date(), sales_all["orderDate"].max().date()
date_range = st.sidebar.date_input("Order date", (dmin, dmax), min_value=dmin, max_value=dmax)
if isinstance(date_range, tuple) and len(date_range) == 2:
    d0, d1 = date_range
else:
    d0, d1 = dmin, dmax


def multi(label, col):
    opts = sorted(sales_all[col].dropna().unique())
    return st.sidebar.multiselect(label, opts, placeholder="All")


f_cat = multi("Category", "categoryName")
f_cty = multi("Customer country", "customerCountry")
f_emp = multi("Employee", "employeeName")
f_shp = multi("Shipper", "shipper")

df = sales_all[(sales_all["orderDate"].dt.date >= d0) & (sales_all["orderDate"].dt.date <= d1)]
for col, sel in (("categoryName", f_cat), ("customerCountry", f_cty), ("employeeName", f_emp), ("shipper", f_shp)):
    if sel:
        df = df[df[col].isin(sel)]

if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

orders = order_level(df)

# ----------------------------------------------------------------------------
# Header KPIs
# ----------------------------------------------------------------------------
st.title("Brand Traders – Sales Analytics")
st.caption(f"{d0:%d %b %Y} → {d1:%d %b %Y}  •  {len(df):,} order lines  •  revenue = unit price × qty × (1 − discount)")

rev = df["revenue"].sum()
n_orders = orders["orderID"].nunique()
aov = rev / n_orders
disc_total = df["discountAmt"].sum()
shipped = orders.dropna(subset=["shippedDate"])
late_pct = shipped["late"].astype(float).mean() * 100 if len(shipped) else 0.0

k = st.columns(6)
k[0].metric("Revenue", money(rev))
k[1].metric("Orders", f"{n_orders:,}")
k[2].metric("Avg order value", money(aov))
k[3].metric("Customers", f"{df['customerID'].nunique():,}")
k[4].metric("Discounts given", money(disc_total), f"{disc_total / df['gross'].sum():.1%} of gross", delta_color="off")
k[5].metric("Late deliveries", f"{late_pct:.1f}%")

tabs = st.tabs(["📈 Overview", "🛒 Products & Categories", "👥 Customers", "🌍 Geography",
                "🧑‍💼 Employees", "🚚 Shipping", "📝 Report", "🗂️ Data"])

# ----------------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------------
with tabs[0]:
    monthly = df.groupby("month").agg(revenue=("revenue", "sum"), orders=("orderID", "nunique")).reset_index()
    monthly["MoM %"] = monthly["revenue"].pct_change() * 100

    fig = go.Figure()
    fig.add_bar(x=monthly["month"], y=monthly["revenue"], name="Revenue", marker_color="#4C78A8")
    fig.add_scatter(x=monthly["month"], y=monthly["orders"], name="Orders", yaxis="y2",
                    mode="lines+markers", line=dict(color="#F58518"))
    fig.update_layout(title="Monthly revenue & order count", yaxis=dict(title="Revenue ($)"),
                      yaxis2=dict(title="Orders", overlaying="y", side="right", showgrid=False),
                      legend=dict(orientation="h", y=1.12), height=420)
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        yearly = df.groupby("year").agg(revenue=("revenue", "sum"), orders=("orderID", "nunique")).reset_index()
        yearly["year"] = yearly["year"].astype(str)
        st.plotly_chart(px.bar(yearly, x="year", y="revenue", text_auto=".3s", title="Revenue by year"),
                        width="stretch")
    with c2:
        season = df.groupby(["monthNum", "year"])["revenue"].sum().reset_index()
        season["year"] = season["year"].astype(str)
        st.plotly_chart(px.line(season, x="monthNum", y="revenue", color="year", markers=True,
                                title="Seasonality: revenue by calendar month",
                                labels={"monthNum": "Month"}), width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        wd = orders.assign(wd=orders["orderDate"].dt.day_name()).groupby("wd")["revenue"].sum().reindex(order).dropna().reset_index()
        st.plotly_chart(px.bar(wd, x="wd", y="revenue", title="Revenue by weekday", labels={"wd": ""}),
                        width="stretch")
    with c4:
        st.plotly_chart(px.histogram(orders, x="revenue", nbins=40, title="Order value distribution",
                                     labels={"revenue": "Order value ($)"}), width="stretch")

# ----------------------------------------------------------------------------
# Products & Categories
# ----------------------------------------------------------------------------
with tabs[1]:
    cat = df.groupby("categoryName").agg(revenue=("revenue", "sum"), units=("quantity", "sum"),
                                         products=("productID", "nunique")).reset_index()
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.pie(cat, names="categoryName", values="revenue", hole=0.45,
                               title="Revenue share by category"), width="stretch")
    with c2:
        cm = df.groupby(["month", "categoryName"])["revenue"].sum().reset_index()
        st.plotly_chart(px.area(cm, x="month", y="revenue", color="categoryName",
                                title="Category revenue over time"), width="stretch")

    prod = df.groupby(["productName", "categoryName"]).agg(
        revenue=("revenue", "sum"), units=("quantity", "sum"), orders=("orderID", "nunique"),
        avgDiscount=("discount", "mean")).reset_index()
    top_n = st.slider("Top / bottom N products", 5, 25, 10)
    c3, c4 = st.columns(2)
    with c3:
        t = prod.nlargest(top_n, "revenue").sort_values("revenue")
        st.plotly_chart(px.bar(t, x="revenue", y="productName", color="categoryName", orientation="h",
                               title=f"Top {top_n} products by revenue"), width="stretch")
    with c4:
        b = prod.nsmallest(top_n, "revenue").sort_values("revenue", ascending=False)
        st.plotly_chart(px.bar(b, x="revenue", y="productName", color="categoryName", orientation="h",
                               title=f"Bottom {top_n} products by revenue"), width="stretch")

    st.plotly_chart(px.treemap(prod, path=["categoryName", "productName"], values="revenue",
                               title="Revenue treemap (category → product)"), width="stretch")

    c5, c6 = st.columns(2)
    with c5:
        st.plotly_chart(px.scatter(prod, x="units", y="revenue", size="orders", color="categoryName",
                                   hover_name="productName", title="Units sold vs revenue (bubble = # orders)"),
                        width="stretch")
    with c6:
        dd = df.copy()
        dd["discountBand"] = pd.cut(dd["discount"], [-0.001, 0, 0.05, 0.10, 0.15, 0.20, 1],
                                    labels=["0%", "1–5%", "6–10%", "11–15%", "16–20%", ">20%"])
        band = dd.groupby("discountBand", observed=True).agg(avgQty=("quantity", "mean"),
                                                             lines=("orderID", "count")).reset_index()
        st.plotly_chart(px.bar(band, x="discountBand", y="avgQty", text="lines",
                               title="Does discounting lift quantity? (avg qty per line; label = # lines)",
                               labels={"avgQty": "Avg quantity", "discountBand": "Discount band"}),
                        width="stretch")

    disc = df.groupby("discontinued")["revenue"].sum()
    if 1 in disc.index:
        st.info(f"Discontinued products still account for **{money(disc[1])}** "
                f"({disc[1] / disc.sum():.1%}) of revenue in this selection.")

# ----------------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------------
with tabs[2]:
    cust = orders.groupby("customer").agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"),
                                          last=("orderDate", "max"), first=("orderDate", "min")).reset_index()
    cust["aov"] = cust["revenue"] / cust["orders"]
    c1, c2 = st.columns(2)
    with c1:
        t = cust.nlargest(15, "revenue").sort_values("revenue")
        st.plotly_chart(px.bar(t, x="revenue", y="customer", orientation="h", title="Top 15 customers by revenue"),
                        width="stretch")
    with c2:
        p = cust.sort_values("revenue", ascending=False).reset_index(drop=True)
        p["cumShare"] = p["revenue"].cumsum() / p["revenue"].sum() * 100
        p["custShare"] = (p.index + 1) / len(p) * 100
        fig = px.line(p, x="custShare", y="cumShare", title="Pareto: cumulative revenue vs customers (%)",
                      labels={"custShare": "% of customers", "cumShare": "% of revenue"})
        fig.add_hline(y=80, line_dash="dot")
        st.plotly_chart(fig, width="stretch")
        n80 = int((p["cumShare"] < 80).sum() + 1)
        st.caption(f"{n80} customers ({n80 / len(p):.0%}) generate 80% of revenue.")

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(px.histogram(cust, x="orders", nbins=20, title="Customers by number of orders"),
                        width="stretch")
    with c4:
        ref = orders["orderDate"].max() + pd.Timedelta(days=1)
        cust["recencyDays"] = (ref - cust["last"]).dt.days
        st.plotly_chart(px.scatter(cust, x="recencyDays", y="revenue", size="orders", hover_name="customer",
                                   title="Recency vs revenue (top-left = best, bottom-right = at risk)",
                                   labels={"recencyDays": "Days since last order"}), width="stretch")

    st.subheader("Customer table")
    st.dataframe(cust.sort_values("revenue", ascending=False)
                 .assign(revenue=lambda d: d["revenue"].round(0), aov=lambda d: d["aov"].round(0))
                 [["customer", "revenue", "orders", "aov", "first", "last", "recencyDays"]],
                 width="stretch", hide_index=True)

# ----------------------------------------------------------------------------
# Geography
# ----------------------------------------------------------------------------
with tabs[3]:
    geo = orders.groupby("customerCountry").agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"),
                                                customers=("customer", "nunique")).reset_index()
    geo["iso_name"] = geo["customerCountry"].replace(MAP_FIX)
    geo["aov"] = geo["revenue"] / geo["orders"]
    fig = px.choropleth(geo, locations="iso_name", locationmode="country names", color="revenue",
                        hover_name="customerCountry", hover_data=["orders", "customers", "aov"],
                        color_continuous_scale="Blues", title="Revenue by customer country")
    st.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.bar(geo.sort_values("revenue", ascending=False).head(15), x="customerCountry",
                               y="revenue", title="Top countries by revenue"), width="stretch")
    with c2:
        city = df.groupby(["customerCity", "customerCountry"])["revenue"].sum().reset_index().nlargest(15, "revenue")
        st.plotly_chart(px.bar(city, x="revenue", y="customerCity", color="customerCountry", orientation="h",
                               title="Top 15 cities").update_yaxes(categoryorder="total ascending"),
                        width="stretch")
    st.plotly_chart(px.scatter(geo, x="customers", y="aov", size="revenue", hover_name="customerCountry",
                               title="Countries: customer count vs avg order value (bubble = revenue)"),
                    width="stretch")

# ----------------------------------------------------------------------------
# Employees
# ----------------------------------------------------------------------------
with tabs[4]:
    emp = orders.groupby("employeeName").agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"),
                                             customers=("customer", "nunique")).reset_index()
    emp["aov"] = emp["revenue"] / emp["orders"]
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.bar(emp.sort_values("revenue"), x="revenue", y="employeeName", orientation="h",
                               title="Revenue by employee", text_auto=".3s"), width="stretch")
    with c2:
        st.plotly_chart(px.scatter(emp, x="orders", y="aov", size="revenue", hover_name="employeeName",
                                   title="Orders handled vs avg order value"), width="stretch")
    em = df.groupby(["month", "employeeName"])["revenue"].sum().reset_index()
    st.plotly_chart(px.line(em, x="month", y="revenue", color="employeeName", title="Employee revenue over time"),
                    width="stretch")
    ec = df.pivot_table(index="employeeName", columns="categoryName", values="revenue", aggfunc="sum", fill_value=0)
    st.plotly_chart(px.imshow(ec, aspect="auto", color_continuous_scale="Blues",
                              title="Employee × category revenue heatmap"), width="stretch")

# ----------------------------------------------------------------------------
# Shipping
# ----------------------------------------------------------------------------
with tabs[5]:
    ship = orders.groupby("shipper").agg(orders=("orderID", "nunique"), freight=("freight", "sum"),
                                         avgFreight=("freight", "mean"), avgDays=("deliveryDays", "mean"),
                                         lateRate=("late", lambda s: s.dropna().astype(float).mean() * 100)).reset_index()
    k2 = st.columns(3)
    k2[0].metric("Total freight", money(orders["freight"].sum()))
    k2[1].metric("Avg days to ship", f"{orders['deliveryDays'].mean():.1f}")
    k2[2].metric("Unshipped orders", f"{orders['shippedDate'].isna().sum():,}")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.bar(ship, x="shipper", y="orders", title="Orders by shipper", text_auto=True),
                        width="stretch")
    with c2:
        st.plotly_chart(px.bar(ship, x="shipper", y="avgFreight", title="Average freight per order ($)",
                               text_auto=".2f"), width="stretch")
    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(px.box(orders.dropna(subset=["deliveryDays"]), x="shipper", y="deliveryDays",
                               title="Days from order to shipment, by shipper"), width="stretch")
    with c4:
        st.plotly_chart(px.bar(ship, x="shipper", y="lateRate", title="Late delivery rate (%) by shipper",
                               text_auto=".1f"), width="stretch")
    fr = orders.groupby("customerCountry").agg(freight=("freight", "mean"), revenue=("revenue", "mean")).reset_index()
    fr["freightPct"] = fr["freight"] / fr["revenue"] * 100
    st.plotly_chart(px.bar(fr.sort_values("freightPct", ascending=False).head(15), x="customerCountry", y="freightPct",
                           title="Freight as % of order value – top 15 countries"), width="stretch")

# ----------------------------------------------------------------------------
# Report (auto-generated insights)
# ----------------------------------------------------------------------------
with tabs[6]:
    st.header("Analysis report")
    st.caption("Generated automatically from the current filters.")

    top_cat = cat.nlargest(1, "revenue").iloc[0]
    top_prod = prod.nlargest(1, "revenue").iloc[0]
    top_cust = cust.nlargest(1, "revenue").iloc[0]
    top_cty = geo.nlargest(1, "revenue").iloc[0]
    top_emp = emp.nlargest(1, "revenue").iloc[0]
    best_m = monthly.nlargest(1, "revenue").iloc[0]
    worst_m = monthly.nsmallest(1, "revenue").iloc[0]
    n80 = int(((cust.sort_values("revenue", ascending=False)["revenue"].cumsum() / cust["revenue"].sum()) < 0.8).sum() + 1)
    repeat = (cust["orders"] > 1).mean()
    slow = ship.nlargest(1, "avgDays").iloc[0] if ship["avgDays"].notna().any() else None
    lates = ship.nlargest(1, "lateRate").iloc[0] if ship["lateRate"].notna().any() else None

    st.subheader("Headline")
    st.markdown(
        f"- Revenue of **{money(rev)}** from **{n_orders:,} orders** and **{df['customerID'].nunique()} customers**; "
        f"average order value **{money(aov)}**.\n"
        f"- Best month: **{best_m['month']:%b %Y}** ({money(best_m['revenue'])}); "
        f"weakest: **{worst_m['month']:%b %Y}** ({money(worst_m['revenue'])}).\n"
        f"- Discounts cost **{money(disc_total)}** ({disc_total / df['gross'].sum():.1%} of gross sales)."
    )
    if len(yearly) >= 2:
        y = yearly.sort_values("year")
        growth = (y["revenue"].iloc[-1] / y["revenue"].iloc[-2] - 1) * 100
        st.markdown(f"- Latest year in view ({y['year'].iloc[-1]}) vs previous ({y['year'].iloc[-2]}): **{growth:+.1f}%** "
                    "(check for partial years before drawing conclusions).")

    st.subheader("Products")
    st.markdown(
        f"- Top category: **{top_cat['categoryName']}** – {money(top_cat['revenue'])} "
        f"({top_cat['revenue'] / rev:.1%} of revenue).\n"
        f"- Best product: **{top_prod['productName']}** – {money(top_prod['revenue'])}, {int(top_prod['units']):,} units."
    )

    st.subheader("Customers & markets")
    st.markdown(
        f"- Top customer: **{top_cust['customer']}** – {money(top_cust['revenue'])}.\n"
        f"- Revenue is concentrated: **{n80}** customers ({n80 / len(cust):.0%}) generate 80% of sales.\n"
        f"- **{repeat:.0%}** of customers ordered more than once.\n"
        f"- Largest market: **{top_cty['customerCountry']}** – {money(top_cty['revenue'])} "
        f"({top_cty['revenue'] / rev:.1%})."
    )

    st.subheader("Team & fulfilment")
    bullets = [f"- Top employee: **{top_emp['employeeName']}** – {money(top_emp['revenue'])} across {int(top_emp['orders'])} orders."]
    if slow is not None:
        bullets.append(f"- Slowest shipper to dispatch: **{slow['shipper']}** ({slow['avgDays']:.1f} days on average).")
    if lates is not None:
        bullets.append(f"- Highest late-delivery rate: **{lates['shipper']}** ({lates['lateRate']:.1f}%).")
    st.markdown("\n".join(bullets))

    st.subheader("Suggested actions")
    st.markdown(
        "1. Protect and grow the top customers/markets above; build a retention plan for high-value customers with long recency.\n"
        "2. Review discount policy: compare the discount-band chart – if quantity does not rise with discount, tighten it.\n"
        "3. Rationalise the bottom-N products and any discontinued items still selling.\n"
        "4. Investigate shippers with higher late rates or longer dispatch times; consider rebalancing volume.\n"
        "5. Use the seasonality chart to plan inventory and staffing for peak months."
    )

# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
with tabs[7]:
    st.subheader("Joined dataset (order line level)")
    st.caption("orders ⟶ order_details ⟶ products ⟶ categories, plus customers, employees and shippers.")
    cols = ["orderID", "orderDate", "customer", "customerCountry", "employeeName", "shipper", "categoryName",
            "productName", "unitPrice", "quantity", "discount", "gross", "discountAmt", "revenue", "freight",
            "requiredDate", "shippedDate", "deliveryDays", "late"]
    show = df[cols].sort_values("orderDate")
    st.dataframe(show, width="stretch", hide_index=True)
    st.download_button("⬇️ Download joined data (CSV)", show.to_csv(index=False).encode("utf-8"),
                       "brand_traders_joined.csv", "text/csv")
    with st.expander("Table relationships"):
        st.code(
            "orders.customerID    → customers.customerID\n"
            "orders.employeeID    → employees.employeeID\n"
            "orders.shipperID     → shippers.shipperID\n"
            "order_details.orderID   → orders.orderID\n"
            "order_details.productID → products.productID\n"
            "products.categoryID  → categories.categoryID\n"
            "employees.reportsTo  → employees.employeeID (manager)"
        )
