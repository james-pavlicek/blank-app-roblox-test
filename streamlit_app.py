# app.py
import re
import json
import requests
import pandas as pd
import streamlit as st
import unicodedata

# ---------- Config ----------
DEVEX_RATE_USD_PER_R = 0.0038  # Fixed conversion: $0.0038 per Robux
L1_WEIGHT = 0.70               # 70% L1, 30% L2 when both exist

# ---------- Page ----------
st.set_page_config(page_title="Roblox Game Details + Lifetime Estimate", page_icon="🎮", layout="centered")
st.title("🎮 Roblox Game Details + Lifetime Earnings Estimate (USD + Robux)")


url = st.text_input(
    "Roblox game URL",
    placeholder="https://www.roblox.com/games/",
)

# ---------- Genre helpers ----------
def _normalize_label(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

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

def _mean_band_of_all_l1():
    vals = list(DEFAULT_ARPV_BY_L1.values())
    if not vals:
        return (0.20, 0.40, 0.80)
    lows  = sum(v[0] for v in vals) / len(vals)
    bases = sum(v[1] for v in vals) / len(vals)
    highs = sum(v[2] for v in vals) / len(vals)
    return (lows, bases, highs)

MEAN_BAND_ALL_L1 = _mean_band_of_all_l1()

def _mix_bands(b1, b2, w_l1=L1_WEIGHT):
    """Weighted blend of two (low, base, high) tuples: w*L1 + (1-w)*L2."""
    w_l2 = 1.0 - w_l1
    return (w_l1*b1[0] + w_l2*b2[0],
            w_l1*b1[1] + w_l2*b2[1],
            w_l1*b1[2] + w_l2*b2[2])

def _arpv_band_for(genre_l1: str | None, genre_l2: str | None):
    """
    Returns a (low, base, high) ARPV band using:
      - 70% L1 + 30% L2 if both exist (and L2 override exists)
      - 100% L1 if only L1 exists
      - average of all L1 bands if neither recognized
    """
    nl1 = _normalize_label(genre_l1)
    nl2 = _normalize_label(genre_l2)
    if nl1 in DEFAULT_ARPV_BY_L1:
        l1_band = DEFAULT_ARPV_BY_L1[nl1]
        l2_band = L2_OVERRIDES.get((nl1, nl2))
        if l2_band:
            return _mix_bands(l1_band, l2_band, w_l1=L1_WEIGHT)  # 70% L1 + 30% L2
        return l1_band  # 100% L1
    # No L1 (or unrecognized): use average of all L1s
    return MEAN_BAND_ALL_L1

def _fmt_robux(x: float) -> str:
    return f"{x:,.0f} R$"

def _fmt_usd(x: float) -> str:
    return f"${x:,.2f}"

# ---------- Network helpers ----------
def extract_place_id_from_games_url(s: str) -> int | None:
    if not s:
        return None
    m = re.search(r"/games/(\d+)", s)
    return int(m.group(1)) if m else None

@st.cache_data(ttl=300)
def get_universe_id(place_id: int) -> dict:
    url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=120)
def get_game_details(universe_id: int) -> dict:
    url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def to_flat_dataframe(games_json: dict) -> pd.DataFrame:
    """Flatten the /v1/games response into a tidy DataFrame."""
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
    cols_to_rename = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(columns=cols_to_rename)

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

# ---------- Main ----------
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
                        # Summary (no DataFrame)
                        row = df.iloc[0].to_dict()
                        st.subheader("Game Details (summary)")
                        colA, colB, colC = st.columns(3)
                        with colA:
                            st.markdown(f"**Name**: {row.get('name','—')}")
                            st.markdown(f"**Universe ID**: {row.get('universeId','—')}")
                            st.markdown(f"**Root Place ID**: {row.get('rootPlaceId','—')}")
                        with colB:
                            st.markdown(f"**Genre L1**: {row.get('genre_l1') or row.get('genre') or '—'}")
                            st.markdown(f"**Genre L2**: {row.get('genre_l2') or '—'}")
                            st.markdown(f"**Max Players**: {row.get('maxPlayers','—')}")
                        with colC:
                            st.markdown(f"**Visits**: {row.get('visits', '—'):,}" if row.get('visits') is not None else "**Visits**: —")
                            st.markdown(f"**Playing (now)**: {row.get('playing','—')}")
                            st.markdown(f"**Favorites**: {row.get('favoritedCount','—'):,}" if row.get('favoritedCount') is not None else "**Favorites**: —")

                        # ===== MONEY (USD primary, Robux below) =====
                        st.markdown("---")
                        st.header("💰 Estimated Lifetime Earnings")
                        st.caption("Computed as: visits × blended ARPV (70% L1 + 30% L2 if available; else 100% L1; else average of all L1 bands). Converted at $0.0038/R$.")
                        estimates = []
                        for _, r in df.iterrows():
                            visits = int(r.get("visits") or 0)
                            l1 = r.get("genre_l1") or r.get("genre") or ""
                            l2 = r.get("genre_l2") or ""
                            low_rpv, base_rpv, high_rpv = _arpv_band_for(l1, l2)
                            low_r = visits * low_rpv
                            base_r = visits * base_rpv
                            high_r = visits * high_rpv
                            estimates.append({
                                "name": r.get("name", "Experience"),
                                "visits": visits,
                                "genre_l1": l1,
                                "genre_l2": l2,
                                "low_usd": low_r * DEVEX_RATE_USD_PER_R,
                                "base_usd": base_r * DEVEX_RATE_USD_PER_R,
                                "high_usd": high_r * DEVEX_RATE_USD_PER_R,
                                "low_r": low_r,
                                "base_r": base_r,
                                "high_r": high_r,
                            })

                        for est in estimates:
                            st.subheader(est["name"])
                            st.markdown(
                                f"**Genre**: {est['genre_l1'] or '—'}"
                                + (f" ▸ {est['genre_l2']}" if est['genre_l2'] else "")
                                + f"  |  **Visits**: {est['visits']:,}"
                            )
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                st.metric("Low", _fmt_usd(est["low_usd"]))
                                st.caption(_fmt_robux(est["low_r"]))
                            with c2:
                                st.metric("Base", _fmt_usd(est["base_usd"]))
                                st.caption(_fmt_robux(est["base_r"]))
                            with c3:
                                st.metric("High", _fmt_usd(est["high_usd"]))
                                st.caption(_fmt_robux(est["high_r"]))

                        # ===== Raw JSON AFTER money =====
                        st.markdown("---")
                        st.subheader("Raw JSON: /v1/games")
                        st.code(json.dumps(games_resp, indent=2), language="json")

                except requests.HTTPError as e:
                    st.error(f"Game details fetch failed (HTTP {e.response.status_code}).")
                    with st.expander("Games API raw response"):
                        body = e.response.text[:1500] if e.response is not None else ""
                        st.code(body or "(no body)", language="text")
                except requests.RequestException as e:
                    st.error(f"Network error during game details fetch: {e}")

# ---------- Footer ----------
st.markdown("---")
st.caption(
    "Flow: URL → placeId → /universes/v1/places/{placeId}/universe → universeId → "
    "/v1/games?universeIds={universeId} → USD estimate (Robux shown below)."
)
