# app.py — Karty z PNG (bez ustawień, stabilne klucze checkboxów, fixed hand=3)
# uruchom: python -m pip install streamlit pillow
#          python -m streamlit run app.py

import streamlit as st
from PIL import Image
from io import BytesIO
import random, os, glob

st.set_page_config(page_title="Karty z PNG", layout="wide")
dark_css = """
<style>
/* główne tło aplikacji */
div[data-testid="stAppViewContainer"] {
    background-color: #111 !important;
    color: #eee !important;
}

/* wewnętrzny kontener bloków */
div[data-testid="stAppViewBlockContainer"] {
    background-color: #111 !important;
    color: #eee !important;
}

/* sidebar */
section[data-testid="stSidebar"] {
    background-color: #1a1a1a !important;
    color: #eee !important;
}

/* tekst, nagłówki */
h1, h2, h3, h4, h5, h6, p, span, label {
    color: #eee !important;
}

/* przyciski */
.stButton button {
    background-color: #333 !important;
    color: #eee !important;
    border: 1px solid #555;
    border-radius: 8px;
}
.stButton button:hover {
    background-color: #444 !important;
    border-color: #888;
}
</style>
"""
st.markdown(dark_css, unsafe_allow_html=True)
st.markdown(
    "<style>#MainMenu {visibility:hidden;} footer {visibility:hidden;}</style>",
    unsafe_allow_html=True
)



DEFAULT_CARDS_DIR = "cards"
HAND_SIZE = 3  # stała: ręka zawsze 3

# ---------- Utils ----------
def load_png_bytes_from_folder(folder: str):
    paths = sorted(glob.glob(os.path.join(folder, "*.png")))
    imgs = []
    for p in paths:
        with Image.open(p) as im:
            buf = BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
            imgs.append(buf.getvalue())
    return imgs, paths

def ensure_state():
    for k, v in {
        "images": [],
        "image_paths": [],
        "deck": [],
        "discard": [],
        "hand": [],
        "exhausted": False,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

def init_deck(images, image_paths):
    st.session_state.images = images
    st.session_state.image_paths = image_paths
    st.session_state.deck = list(range(len(images)))
    random.shuffle(st.session_state.deck)
    st.session_state.discard = []
    st.session_state.hand = []
    st.session_state.exhausted = False
    clear_all_discard_flags()

def draw_to_hand_size():
    hand = st.session_state.hand
    deck = st.session_state.deck
    target = HAND_SIZE
    while len(hand) < target and deck:
        nxt = deck.pop()
        if nxt not in hand:
            hand.append(nxt)
    st.session_state.exhausted = len(hand) < target and len(deck) == 0
    clear_obsolete_discard_flags()  # sprzątaj flagi

def counters():
    st.caption(
        f"Ręka: **{len(st.session_state.hand)}** | "
        f"W talii: **{len(st.session_state.deck)}** | "
        f"Odrzucone: **{len(st.session_state.discard)}** | "
        f"Kart w zestawie: **{len(st.session_state.images)}**"
    )

def discard_key(idx: int) -> str:
    # STABILNY klucz po ID karty w talii
    return f"discard_card_{idx}"

def clear_obsolete_discard_flags():
    """Usuń z session_state flagi kart, których nie ma już ani w ręce, ani w talii."""
    alive = set(st.session_state.hand) | set(st.session_state.deck)
    to_del = [
        k for k in list(st.session_state.keys())
        if k.startswith("discard_card_")
        and (int(k.split("_")[-1]) not in alive)
    ]
    for k in to_del:
        st.session_state.pop(k, None)

def clear_all_discard_flags():
    for k in [k for k in list(st.session_state.keys()) if k.startswith("discard_card_")]:
        st.session_state.pop(k, None)

def render_hand_ui():
    hand = st.session_state.hand
    images = st.session_state.images
    cols = st.columns(max(HAND_SIZE, 1), gap="small")

    for pos, idx in enumerate(hand):
        with cols[pos % max(HAND_SIZE, 1)]:
            img = Image.open(BytesIO(images[idx]))
            # używaj use_container_width zamiast deprecated use_column_width
            st.image(img, use_container_width=True)
            # CHECKBOX ma klucz po ID karty, nie po pozycji
            st.checkbox("Odrzuć tę kartę", key=discard_key(idx))

# ---------- App ----------
def main():
    ensure_state()
    st.title("Karty z PNG")

    # Auto-init z 'cards/'
    if not st.session_state.images:
        if os.path.isdir(DEFAULT_CARDS_DIR):
            imgs, paths = load_png_bytes_from_folder(DEFAULT_CARDS_DIR)
            if imgs:
                init_deck(imgs, paths)
            else:
                st.error(f"Brak plików .png w: '{DEFAULT_CARDS_DIR}'")
                st.stop()
        else:
            st.error(f"Nie znaleziono folderu '{DEFAULT_CARDS_DIR}'. Utwórz go i wrzuć PNG.")
            st.stop()

    if not st.session_state.hand:
        draw_to_hand_size()

    counters()
    render_hand_ui()
    counters()

    left, mid, right = st.columns([1, 0.1, 1])

    # 1) Odrzuć zaznaczone (bez dobierania)
    if left.button("Odrzuć zaznaczone"):
        removed_any = False
        for idx in list(st.session_state.hand):
            if st.session_state.get(discard_key(idx), False):
                st.session_state.hand.remove(idx)
                st.session_state.discard.append(idx)
                st.session_state.pop(discard_key(idx), None)
                removed_any = True
        if not removed_any:
            st.info("Nie zaznaczono żadnej karty do odrzucenia.")
        st.session_state.exhausted = (
            len(st.session_state.hand) < HAND_SIZE and len(st.session_state.deck) == 0
        )

    # 2) Dobierz do pełnej ręki
    if right.button("Dobierz do pełnej ręki", disabled=not st.session_state.deck):
        draw_to_hand_size()

    # 3) Reset rundy (przetasuj aktualny zestaw)
    if st.button("🔄 Reset rundy"):
        if st.session_state.images:
            init_deck(st.session_state.images, st.session_state.image_paths)
            st.success("Zresetowano rundę i przetasowano talię.")

    if st.session_state.exhausted:
        st.warning("Talia się skończyła. Odrzucone karty nie wracają do puli — nowych już nie dobierzesz.")

if __name__ == "__main__":
    main()



