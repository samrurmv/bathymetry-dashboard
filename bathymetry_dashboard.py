import streamlit as st
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone
import time
import json

# ----------------------------
# Config
# ----------------------------
API_URL = "https://bathymetry-api.onrender.com/simulate-multi?vessel_count=5&num_points=20"
MBS = 10  # Minimum safe depth

# ----------------------------
# Fetching with Retry
# ----------------------------
def fetch_data_with_retry(url, retries=1, delay=5):
    for attempt in range(retries + 1):
        try:
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            if attempt < retries:
                time.sleep(delay)
            else:
                raise e

# ----------------------------
# Hazard Categorization
# ----------------------------
def categorize(row):
    if row["is_restricted"]:
        return "Restricted Zone", "⛔", "#FF4500"
    elif row["is_wreck"]:
        return "Wreck", "⚫", "#000000"
    elif row["is_rock"]:
        return "Rock", "🔺", "#FF0000"
    elif row["depth"] < MBS:
        return "Shallow Water", "⚠️", "#1E90FF"
    elif row["depth"] >= 30:
        return "Deep Water", "—", "#FFFFFF"
    else:
        return "Safe Water", "✓", "#32CD32"

def hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return [int(h[i:i+2], 16) for i in (0, 2, 4)] + [160]  # 160 alpha transparency

# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Bathymetry Hazard Dashboard", layout="wide")
st.title("🌊 Bathymetry Hazard Dashboard")
st.caption(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

with st.spinner("Fetching data... (or waking up Render API)"):
    try:
        vessel_data = fetch_data_with_retry(API_URL, retries=1, delay=7)
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        st.stop()

# ----------------------------
# Data Processing
# ----------------------------
all_points = []
for vessel in vessel_data.get("vessels", []):
    all_points.extend(vessel["data"])

df = pd.DataFrame(all_points)

# Convert timestamp to datetime
df["timestamp"] = pd.to_datetime(df["timestamp"])

# Simulate hazard flags
df["is_rock"] = df["depth"] < 1.5
df["is_wreck"] = (df["depth"] >= 3) & (df["depth"] < 5) & (df.index % 7 == 0)
df["is_restricted"] = df.index % 13 == 0

# Apply categorization
df[["category", "symbol", "color"]] = df.apply(categorize, axis=1, result_type="expand")

# Prepare the rgb column as list of lists for pydeck
df["rgb"] = df["color"].apply(hex_to_rgb).tolist()

# ----------------------------
# Sidebar Filters
# ----------------------------
st.sidebar.header("🔎 Filters")

vessel_options = sorted(df["vessel_id"].unique())
selected_vessels = st.sidebar.multiselect("Vessel(s)", vessel_options, default=vessel_options)

hazard_options = df["category"].unique().tolist()
selected_hazards = st.sidebar.multiselect("Hazards", hazard_options, default=hazard_options)

min_time, max_time = df["timestamp"].min().to_pydatetime(), df["timestamp"].max().to_pydatetime()
time_range = st.sidebar.slider(
    "Time Range", min_value=min_time, max_value=max_time,
    value=(min_time, max_time), format="YYYY-MM-DD HH:mm"
)

# Apply filters
df_filtered = df[
    (df["vessel_id"].isin(selected_vessels)) &
    (df["category"].isin(selected_hazards)) &
    (df["timestamp"] >= time_range[0]) &
    (df["timestamp"] <= time_range[1])
]

# ----------------------------
# Data Display
# ----------------------------
st.subheader("📋 Filtered Bathymetry Data")
st.dataframe(df_filtered[["vessel_id", "latitude", "longitude", "depth", "category", "symbol", "timestamp"]])

# ----------------------------
# Map Display
# ----------------------------
st.subheader("🗺️ Hazard Map")

if not df_filtered.empty:
    midpoint = (df_filtered["latitude"].mean(), df_filtered["longitude"].mean())
else:
    midpoint = (0, 0)

layer = pdk.Layer(
    "ScatterplotLayer",
    data=df_filtered,
    get_position='[longitude, latitude]',
    get_fill_color='rgb',  # Pass column with list of RGBA
    get_radius=200,
    pickable=True,
)

view_state = pdk.ViewState(
    latitude=midpoint[0],
    longitude=midpoint[1],
    zoom=6,
    pitch=30,
)

tooltip = {
    "html": "<b>Vessel:</b> {vessel_id} <br/> <b>Depth:</b> {depth} m <br/> <b>Hazard:</b> {category} {symbol}",
    "style": {"color": "white"}
}

st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip))

# ----------------------------
# Export Options
# ----------------------------
st.subheader("📤 Export Filtered Data")

col1, col2 = st.columns(2)

with col1:
    csv = df_filtered.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, "bathymetry_data.csv", "text/csv")

with col2:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
                "properties": {
                    "vessel_id": row["vessel_id"],
                    "depth": row["depth"],
                    "category": row["category"],
                    "timestamp": row["timestamp"].isoformat()
                },
            }
            for _, row in df_filtered.iterrows()
        ],
    }
    st.download_button("Download GeoJSON", json.dumps(geojson), "bathymetry_data.geojson", "application/geo+json")

# ----------------------------
# Legend
# ----------------------------
st.markdown("### 🧭 Legend (IHO S-52 Hazard Markings)")
st.markdown("""
| Symbol | Category         | Color      | Description                                |
|--------|------------------|------------|--------------------------------------------|
| ⚠️      | Shallow Water     | `#1E90FF`  | Depth < safe depth (MBS)                   |
| ✓      | Safe Water        | `#32CD32`  | Safe to navigate                           |
| —      | Deep Water        | `#FFFFFF`  | Depth > 30m                                |
| 🔺      | Rocks             | `#FF0000`  | Fixed hazards                              |
| ⚫      | Wrecks            | `#000000`  | Shipwrecks                                 |
| ⛔      | Restricted Zone   | `#FF4500`  | No-entry zones                             |
""")
