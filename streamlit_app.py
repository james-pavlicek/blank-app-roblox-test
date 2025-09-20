# app.py
import re
import json
import requests
import pandas as pd
import streamlit as st
import unicodedata

# ---------- Page ----------
st.set_page_config(page_title="Roblox Game Details + Lifetime Estimate", page_icon="🎮", layout="centered")
st.title("🎮 Roblox Game Details + Lifetime Earnings Estimate (Robux only)")

st.write("Paste a Roblox game URL like:")
st.code("https://www.roblox.com/games/76059555697165/Slimera-BETA-1-2", language="text")

url = st.text_input(
    "Roblox game URL",
    placeholder="https://www.roblox.com/games/76059555697165/Slimera-BETA-1-2",
)

# ---------- Genre taxonomy + helpers ----------
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

def _arpv_band_for(genre_l1: str | None, genre_l2: str | None):
    nl1 = _normalize_label(genre_l1)
    nl2 = _normalize_label(genre_l2)
    if nl1 in DEFAULT_ARPV_BY_L1:
        if nl2 and (nl1, nl2) in L2_OVERRIDES:
            return L2_OVERRIDES[(nl1, nl2)]
        return DEFAULT_ARPV_BY_L1[nl1]
    return (0.20, 0.40, 0.80)  # global fallback

def _fmt_robux(x: float) -> str:
    return f"{x:,.0f} R$"

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

                        # ===== MONEY SECTION (moved ABOVE Raw JSON) =====
                        st.markdown("---")
                        st.header("💰 Estimated Lifetime Earnings (Robux only)")
                        st.caption("Computed as: visits × ARPV (low/base/high) based on Genre L1/L2.")
                        estimates = []
                        for _, r in df.iterrows():
                            visits = int(r.get("visits") or 0)
                            l1 = r.get("genre_l1") or r.get("genre") or ""
                            l2 = r.get("genre_l2") or ""
                            low, base, high = _arpv_band_for(l1, l2)
                            estimates.append({
                                "name": r.get("name", "Experience"),
                                "visits": visits,
                                "genre_l1": l1,
                                "genre_l2": l2,
                                "low": visits * low,
                                "base": visits * base,
                                "high": visits * high,
                                "low_arpv": low,
                                "base_arpv": base,
                                "high_arpv": high,
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
                                st.metric("Low", _fmt_robux(est["low"]), help=f"ARPV={est['low_arpv']}")
                            with c2:
                                st.metric("Base", _fmt_robux(est["base"]), help=f"ARPV={est['base_arpv']}")
                            with c3:
                                st.metric("High", _fmt_robux(est["high"]), help=f"ARPV={est['high_arpv']}")

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
    "/v1/games?universeIds={universeId} → Robux-only lifetime estimate using ARPV bands."
)
