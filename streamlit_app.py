# app.py
import re
import json
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import streamlit as st

# ---------- Page ----------
st.set_page_config(page_title="Roblox Game Details + Players Over Time", page_icon="🎮", layout="centered")
st.title("🎮 Roblox Game Details + Players Over Time")

st.write("Paste a Roblox game URL like:")
st.code("https://www.roblox.com/games/76059555697165/Slimera-BETA-1-2", language="text")

url = st.text_input(
    "Roblox game URL",
    placeholder="https://www.roblox.com/games/76059555697165/Slimera-BETA-1-2",
)

# ---------- Genre taxonomy from Roblox docs ----------
# We'll normalize labels so our lookup is robust to casing/punctuation differences.
import math
import unicodedata
import string

def _normalize_label(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    # keep letters/numbers/& and spaces; collapse whitespace
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

GENRE_TAXONOMY = {
    "Action": ["Battlegrounds & Fighting", "Music & Rhythm", "Open World Action"],
    "Adventure": ["Exploration", "Scavenger Hunt", "Story"],
    "Education": [],
    "Entertainment": ["Music & Audio", "Showcase & Hub", "Video"],
    "Obby & platformer": ["Classic Obby", "Runner", "Tower Obby"],
    "Party & casual": ["Childhood Game", "Coloring & Drawing", "Minigame", "Quiz"],
    "Puzzle": ["Escape Room", "Match & Merge", "Word"],
    "RPG": ["Action RPG", "Open World & Survival RPG", "Turn-based RPG"],
    "Roleplay & avatar sim": ["Animal Sim", "Dress Up", "Life", "Morph Roleplay", "Pet Care"],
    "Shooter": ["Battle Royale", "Deathmatch Shooter", "PvE Shooter"],
    "Shopping": ["Avatar Shopping"],
    "Simulation": ["Idle", "Incremental Simulator", "Physics Sim", "Sandbox", "Tycoon", "Vehicle Sim"],
    "Social": [],
    "Sports & racing": ["Racing", "Sports"],
    "Strategy": ["Board & Card Games", "Tower Defense"],
    "Survival": ["1 vs All", "Escape"],
    "Utility & other": [],
}
# Build a normalized lookup for L1 and L2
TAXO_NORM = {
    _normalize_label(k): [_normalize_label(x) for x in v]
    for k, v in GENRE_TAXONOMY.items()
}

# ---------- ARPV (Robux per visit) bands ----------
# Defaults by L1; L2 inherits unless an override is specified.
DEFAULT_ARPV_BY_L1 = {
    _normalize_label("Obby & platformer"): (0.05, 0.15, 0.30),
    _normalize_label("Party & casual"):    (0.05, 0.15, 0.30),
    _normalize_label("Puzzle"):            (0.10, 0.25, 0.50),
    _normalize_label("Education"):         (0.02, 0.10, 0.20),
    _normalize_label("Entertainment"):     (0.02, 0.08, 0.20),
    _normalize_label("Simulation"):        (0.20, 0.50, 1.00),
    _normalize_label("RPG"):               (0.50, 1.00, 2.00),
    _normalize_label("Action"):            (0.30, 0.70, 1.50),
    _normalize_label("Adventure"):         (0.10, 0.40, 0.80),
    _normalize_label("Roleplay & avatar sim"): (0.05, 0.20, 0.60),
    _normalize_label("Shooter"):           (0.40, 0.80, 1.80),
    _normalize_label("Shopping"):          (0.01, 0.05, 0.10),
    _normalize_label("Social"):            (0.02, 0.10, 0.20),
    _normalize_label("Sports & racing"):   (0.10, 0.30, 0.70),
    _normalize_label("Strategy"):          (0.10, 0.30, 0.60),
    _normalize_label("Survival"):          (0.20, 0.60, 1.20),
    _normalize_label("Utility & other"):   (0.01, 0.05, 0.10),
}
# Optional L2 overrides (use normalized keys)
L2_OVERRIDES = {
    (_normalize_label("Action"), _normalize_label("Battlegrounds & Fighting")): (0.50, 0.90, 1.50),
    (_normalize_label("Action"), _normalize_label("Music & Rhythm")):           (0.10, 0.30, 0.60),
    (_normalize_label("Action"), _normalize_label("Open World Action")):        (0.40, 0.80, 1.40),

    (_normalize_label("RPG"), _normalize_label("Action RPG")):                  (0.70, 1.20, 2.20),
    (_normalize_label("RPG"), _normalize_label("Open World & Survival RPG")):   (0.40, 0.80, 1.60),
    (_normalize_label("RPG"), _normalize_label("Turn-based RPG")):              (0.30, 0.70, 1.20),

    (_normalize_label("Simulation"), _normalize_label("Incremental Simulator")): (0.40, 0.70, 1.50),
    (_normalize_label("Simulation"), _normalize_label("Tycoon")):                (0.30, 0.60, 1.20),
    (_normalize_label("Simulation"), _normalize_label("Vehicle Sim")):           (0.10, 0.40, 0.80),
    (_normalize_label("Simulation"), _normalize_label("Sandbox")):               (0.05, 0.20, 0.50),

    (_normalize_label("Obby & platformer"), _normalize_label("Classic Obby")):  (0.05, 0.12, 0.25),
    (_normalize_label("Obby & platformer"), _normalize_label("Tower Obby")):    (0.08, 0.18, 0.30),

    (_normalize_label("Party & casual"), _normalize_label("Minigame")):         (0.08, 0.20, 0.40),

    (_normalize_label("Puzzle"), _normalize_label("Escape Room")):              (0.10, 0.20, 0.40),

    (_normalize_label("Roleplay & avatar sim"), _normalize_label("Pet Care")):  (0.20, 0.40, 1.20),

    (_normalize_label("Shooter"), _normalize_label("Battle Royale")):           (0.60, 1.00, 1.80),
    (_normalize_label("Shooter"), _normalize_label("Deathmatch Shooter")):      (0.50, 0.90, 1.60),
    (_normalize_label("Shooter"), _normalize_label("PvE Shooter")):             (0.30, 0.70, 1.40),

    (_normalize_label("Strategy"), _normalize_label("Tower Defense")):          (0.30, 0.60, 1.20),

    (_normalize_label("Survival"), _normalize_label("1 vs All")):               (0.30, 0.70, 1.40),
    (_normalize_label("Survival"), _normalize_label("Escape")):                 (0.20, 0.60, 1.20),
}

def _arpv_band_for(genre_l1: str | None, genre_l2: str | None):
    """Return (low, base, high) ARPV by normalized L1/L2 with sensible fallbacks."""
    nl1 = _normalize_label(genre_l1)
    nl2 = _normalize_label(genre_l2)
    if nl1 in DEFAULT_ARPV_BY_L1:
        if nl2 and (nl1, nl2) in L2_OVERRIDES:
            return L2_OVERRIDES[(nl1, nl2)]
        return DEFAULT_ARPV_BY_L1[nl1]
    # Fallback if unrecognized L1
    return (0.20, 0.40, 0.80)

# ---------- Helpers ----------
def extract_place_id_from_games_url(s: str) -> int | None:
    """Extract placeId from URLs like /games/{placeId}/..."""
    if not s:
        return None
    m = re.search(r"/games/(\d+)", s)
    return int(m.group(1)) if m else None

@st.cache_data(ttl=300)
def get_universe_id(place_id: int) -> dict:
    """Call place -> universe mapping endpoint. Returns parsed JSON."""
    url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()  # {"universeId": <int>}

@st.cache_data(ttl=120)
def get_game_details(universe_id: int) -> dict:
    """Call games endpoint with universeIds. Returns parsed JSON."""
    url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()  # {"data":[{...}]}

def to_flat_dataframe(games_json: dict) -> pd.DataFrame:
    """Flatten the /v1/games response."""
    data = games_json.get("data", [])
    if not isinstance(data, list):
        data = []
    if not data:
        return pd.DataFrame()
    df = pd.json_normalize(data, sep=".", max_level=2)
    rename_map = {
        "id": "universeId",
        "rootPlaceId": "rootPlaceId",
        "name": "name",
        "description": "description",
        "creator.id": "creator.id",
        "creator.name": "creator.name",
        "creator.type": "creator.type",
        "playing": "playing",
        "visits": "visits",
        "maxPlayers": "maxPlayers",
        "created": "created",
        "updated": "updated",
        "price": "price",
        "favoritedCount": "favoritedCount",
        "universeAvatarType": "universeAvatarType",
        "genre": "genre",
        "genre_l1": "genre_l1",
        "genre_l2": "genre_l2",
        "isAllGenre": "isAllGenre",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    preferred_order = [
        "universeId", "rootPlaceId", "name", "description",
        "creator.name", "creator.type", "creator.id",
        "playing", "visits", "maxPlayers",
        "favoritedCount", "price",
        "genre", "genre_l1", "genre_l2", "isAllGenre", "universeAvatarType",
        "created", "updated",
    ]
    ordered_cols = [c for c in preferred_order if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in ordered_cols]
    return df[ordered_cols + remaining_cols]

def fetch_current_players(universe_id: int) -> int | None:
    """Returns current 'playing' from /v1/games (snapshot, not historical)."""
    try:
        data = get_game_details(universe_id)
        row = (data.get("data") or [{}])[0]
        return int(row.get("playing")) if row and row.get("playing") is not None else None
    except Exception:
        return None

# ---------- Main: Details ----------
if st.button("Fetch Game Details", type="primary"):
    place_id = extract_place_id_from_games_url(url)
    if not place_id:
        st.error("Couldn’t find a placeId in that URL. It must contain `/games/{placeId}/...`.")
    else:
        st.info(f"Detected placeId: `{place_id}`")
        try:
            uni_resp = get_universe_id(place_id)
        except requests.HTTPError as e:
            st.error(f"Universe lookup failed (HTTP {e.response.status_code}).")
            with st.expander("Universe API raw response"):
                body = e.response.text[:1500] if e.response is not None else ""
                st.code(body or "(no body)", language="text")
        except requests.RequestException as e:
            st.error(f"Network error during universe lookup: {e}")
        else:
            universe_id = uni_resp.get("universeId")
            if not isinstance(universe_id, int):
                st.error("Universe lookup succeeded but no `universeId` was found.")
                with st.expander("Universe API raw response"):
                    st.code(json.dumps(uni_resp, indent=2), language="json")
            else:
                st.success(f"Universe ID: **{universe_id}**")
                try:
                    games_resp = get_game_details(universe_id)
                    df = to_flat_dataframe(games_resp)
                    if df.empty:
                        st.warning("No game data returned for that universeId.")
                    else:
                        st.subheader("Game Details (DataFrame)")
                        st.dataframe(df, use_container_width=True)
                except requests.HTTPError as e:
                    st.error(f"Game details fetch failed (HTTP {e.response.status_code}).")
                    with st.expander("Games API raw response"):
                        body = e.response.text[:1500] if e.response is not None else ""
                        st.code(body or "(no body)", language="text")
                except requests.RequestException as e:
                    st.error(f"Network error during game details fetch: {e}")

                # ---------- NEW: Estimated Lifetime Earnings by Genre ----------
                if 'df' in locals() and not df.empty:
                    st.markdown("---")
                    st.header("💰 Estimated Lifetime Earnings (ARPV × Visits)")
                    st.caption(
                        "We use Roblox's official Genre/Subgenre taxonomy to pick an ARPV (Robux/visit) band. "
                        "These are heuristic bands — calibrate to your own data for best accuracy."
                    )

                    devex_rate = st.number_input(
                        "DevEx USD per Robux (optional for USD conversion)",
                        min_value=0.0, max_value=0.02, value=0.0, step=0.0001, format="%.6f",
                        help="Leave 0 to show Robux only."
                    )

                    # Build an estimates table from the details DF
                    est_rows = []
                    for _, row in df.iterrows():
                        visits = int(row.get("visits") or 0)
                        l1 = row.get("genre_l1") or row.get("genre") or ""
                        l2 = row.get("genre_l2") or ""
                        low, base, high = _arpv_band_for(l1, l2)

                        est = {
                            "universeId": row.get("universeId"),
                            "name": row.get("name"),
                            "visits": visits,
                            "genre_l1": l1,
                            "genre_l2": l2,
                            "arpv_low": low,
                            "arpv_base": base,
                            "arpv_high": high,
                            "est_robux_low": visits * low,
                            "est_robux_base": visits * base,
                            "est_robux_high": visits * high,
                        }
                        if devex_rate > 0:
                            est["est_usd_low"] = est["est_robux_low"] * devex_rate
                            est["est_usd_base"] = est["est_robux_base"] * devex_rate
                            est["est_usd_high"] = est["est_robux_high"] * devex_rate
                        est_rows.append(est)

                    df_est = pd.DataFrame(est_rows)

                    # Order columns for readability
                    cols = [
                        "universeId", "name", "visits", "genre_l1", "genre_l2",
                        "arpv_low", "arpv_base", "arpv_high",
                        "est_robux_low", "est_robux_base", "est_robux_high",
                    ]
                    if devex_rate > 0:
                        cols += ["est_usd_low", "est_usd_base", "est_usd_high"]

                    st.subheader("Estimates (per experience)")
                    st.dataframe(df_est[cols], use_container_width=True)

                # ---------- Players Over Time (unchanged) ----------
                st.markdown("---")
                st.header("👥 Players Over Time")

                key = f"timeseries_{universe_id}"
                if key not in st.session_state:
                    st.session_state[key] = pd.DataFrame(columns=["timestamp", "players"])

                col_a, col_b, col_c = st.columns([1,1,1])
                with col_a:
                    window_label = st.selectbox(
                        "Window",
                        ["7 days", "14 days", "30 days", "90 days", "1 year"],
                        index=0,
                    )
                with col_b:
                    auto_sample = st.toggle("Auto-sample every 60s", value=True, help="Collects a datapoint once per minute while this app tab is open.")
                with col_c:
                    if st.button("Add datapoint now"):
                        cur = fetch_current_players(universe_id)
                        if cur is None:
                            st.warning("Couldn’t fetch current players right now.")
                        else:
                            new_row = {"timestamp": datetime.now(timezone.utc), "players": cur}
                            st.session_state[key] = pd.concat([st.session_state[key], pd.DataFrame([new_row])], ignore_index=True)

                if auto_sample:
                    df_ts = st.session_state[key]
                    should_sample = True
                    if not df_ts.empty:
                        last_ts = pd.to_datetime(df_ts["timestamp"]).max()
                        should_sample = (datetime.now(timezone.utc) - last_ts) >= timedelta(seconds=55)
                    if should_sample:
                        cur = fetch_current_players(universe_id)
                        if cur is not None:
                            new_row = {"timestamp": datetime.now(timezone.utc), "players": cur}
                            st.session_state[key] = pd.concat([st.session_state[key], pd.DataFrame([new_row])], ignore_index=True)
                    # Auto-refresh (same as previous script)
                    st.experimental_rerun()  # comment out if too aggressive

                df_ts = st.session_state[key].copy()
                if not df_ts.empty:
                    df_ts["timestamp"] = pd.to_datetime(df_ts["timestamp"], utc=True)
                    now = datetime.now(timezone.utc)
                    days_map = {"7 days":7, "14 days":14, "30 days":30, "90 days":90, "1 year":365}
                    cutoff = now - timedelta(days=days_map[window_label])
                    df_win = df_ts[df_ts["timestamp"] >= cutoff].sort_values("timestamp")
                else:
                    df_win = df_ts

                st.subheader("Optional: Upload your own history")
                st.caption("CSV with columns: `timestamp` (ISO8601) and `players` (int).")
                uploaded = st.file_uploader("Upload CSV", type=["csv"], accept_multiple_files=False)
                if uploaded is not None:
                    try:
                        csv_df = pd.read_csv(uploaded)
                        csv_df["timestamp"] = pd.to_datetime(csv_df["timestamp"], utc=True, errors="coerce")
                        csv_df = csv_df.dropna(subset=["timestamp", "players"])
                        csv_df["players"] = csv_df["players"].astype(int)
                        merged = pd.concat([st.session_state[key], csv_df], ignore_index=True)
                        merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
                        st.session_state[key] = merged
                        # re-apply window
                        if not merged.empty:
                            merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
                            df_win = merged[merged["timestamp"] >= cutoff]
                        st.success("CSV merged into your current time series.")
                    except Exception as e:
                        st.error(f"Could not parse CSV: {e}")

                if df_win is None or df_win.empty:
                    st.info("No datapoints to chart yet. Add one manually, enable auto-sampling, or upload a CSV.")
                else:
                    st.line_chart(
                        df_win.set_index("timestamp")["players"],
                        use_container_width=True,
                    )

                if not st.session_state[key].empty:
                    csv_bytes = st.session_state[key].to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "Download sampled data (CSV)",
                        data=csv_bytes,
                        file_name=f"players_timeseries_{universe_id}.csv",
                        mime="text/csv",
                    )

# ---------- Footer ----------
st.markdown("---")
st.caption(
    "Flow: URL → placeId → /universes/v1/places/{placeId}/universe → universeId → "
    "/v1/games?universeIds={universeId} → details + ARPV estimates → (optional) CCU sampling."
)
