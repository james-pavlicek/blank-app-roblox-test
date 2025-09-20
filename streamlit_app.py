# app.py
import re
import json
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Roblox Game Details (by URL)", page_icon="🎮", layout="centered")
st.title("🎮 Roblox Game Details from URL")


url = st.text_input(
    "Roblox game URL",
    placeholder="https://www.roblox.com/games/",
)

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
    return r.json()  # expected: {"universeId": <int>}

@st.cache_data(ttl=300)
def get_game_details(universe_id: int) -> dict:
    """Call games endpoint with universeIds. Returns parsed JSON."""
    url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()  # expected: {"data": [ ... ]}

def to_flat_dataframe(games_json: dict) -> pd.DataFrame:
    """
    Flatten the /v1/games response (games_json).
    - Flattens nested fields like creator.*
    - Keeps key fields in readable columns.
    """
    data = games_json.get("data", [])
    if not isinstance(data, list):
        data = []

    if not data:
        return pd.DataFrame()

    # Use json_normalize to flatten nested creator fields
    df = pd.json_normalize(
        data,
        sep=".",
        max_level=2,
    )

    # Optional: rename a few columns for readability, if present
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

    # Reorder columns (only include those that exist)
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
    df = df[ordered_cols + remaining_cols]

    return df

# ---------- UI Flow ----------

if st.button("Fetch Game Details", type="primary"):
    place_id = extract_place_id_from_games_url(url)
    if not place_id:
        st.error("Couldn’t find a placeId in that URL. It must contain `/games/{placeId}/...`.")
    else:
        st.info(f"Detected placeId: `{place_id}`")

        # 1) place -> universe
        try:
            uni_resp = get_universe_id(place_id)
        except requests.HTTPError as e:
            st.error(f"Universe lookup failed (HTTP {e.response.status_code}).")
            with st.expander("Universe API raw response"):
                # try show text if not JSON
                body = e.response.text[:1500] if e.response is not None else ""
                st.code(body or "(no body)", language="text")
        except requests.RequestException as e:
            st.error(f"Network error during universe lookup: {e}")
        else:
            universe_id = uni_resp.get("universeId")
            if not isinstance(universe_id, int):
                st.error("Universe lookup succeeded but no `universeId` field was found.")
                with st.expander("Universe API raw response"):
                    st.code(json.dumps(uni_resp, indent=2), language="json")
            else:
                st.success(f"Universe ID: **{universe_id}**")

                # 2) universe -> game details
                try:
                    games_resp = get_game_details(universe_id)
                except requests.HTTPError as e:
                    st.error(f"Game details fetch failed (HTTP {e.response.status_code}).")
                    with st.expander("Games API raw response"):
                        body = e.response.text[:1500] if e.response is not None else ""
                        st.code(body or "(no body)", language="text")
                except requests.RequestException as e:
                    st.error(f"Network error during game details fetch: {e}")
                else:
                    # Parse and show as DataFrame
                    df = to_flat_dataframe(games_resp)
                    if df.empty:
                        st.warning("No game data returned for that universeId.")
                    else:
                        st.subheader("Game Details (DataFrame)")
                        st.dataframe(df, use_container_width=True)

                    # Always provide raw JSON for transparency/debugging
                    st.subheader("Raw JSON: /v1/games")
                    st.code(json.dumps(games_resp, indent=2), language="json")

# Helpful footer
st.markdown("---")
st.caption(
    "Flow: URL → extract placeId → /universes/v1/places/{placeId}/universe → universeId → "
    "/v1/games?universeIds={universeId} → DataFrame."
)
