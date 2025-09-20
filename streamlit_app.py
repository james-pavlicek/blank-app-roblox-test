# app.py
import re
import json
import requests
import streamlit as st

st.set_page_config(page_title="Roblox Universe ID (Simple)", page_icon="🪐")
st.title("🪐 Roblox Universe ID (Simple)")

url = st.text_input("Roblox game URL", placeholder="https://www.roblox.com/games/")

def extract_place_id_from_games_url(s: str) -> int | None:
    """
    Extracts the placeId from URLs shaped like:
    https://www.roblox.com/games/{placeId}/anything
    """
    if not s:
        return None
    m = re.search(r"/games/(\d+)", s)
    return int(m.group(1)) if m else None

@st.cache_data(ttl=300)
def fetch_universe_id(place_id: int):
    url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()  # expected: {"universeId": <int>}

if st.button("Get Universe ID", type="primary"):
    place_id = extract_place_id_from_games_url(url)
    if not place_id:
        st.error("Couldn’t find a placeId in that URL. It must contain `/games/{placeId}/...`.")
    else:
        st.info(f"Detected placeId: `{place_id}`")
        try:
            data = fetch_universe_id(place_id)
            universe_id = data.get("universeId")
            if isinstance(universe_id, int):
                st.success(f"Universe ID: **{universe_id}**")
                st.markdown(
                    f"- Place page: https://www.roblox.com/games/{place_id}\n"
                    f"- Creator Dashboard: https://create.roblox.com/dashboard/creations/experiences/{universe_id}"
                )
            else:
                st.warning("API responded, but no `universeId` was found.")
            with st.expander("Raw API response"):
                st.code(json.dumps(data, indent=2), language="json")
        except requests.HTTPError as e:
            st.error(f"HTTP error {e.response.status_code}: {e.response.text[:300]}")
        except requests.RequestException as e:
            st.error(f"Network error: {e}")
