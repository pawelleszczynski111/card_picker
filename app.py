# app.py — Karty z PNG (bez PDF)
# wymagania: streamlit, pillow
# uruchom: python -m pip install streamlit pillow
#          python -m streamlit run app.py

import streamlit as st
from PIL import Image
from io import BytesIO
import random, os, glob

st.set_page_config(page_title="Karty z PNG", layout="wide")

DEFAULT_CARDS_DIR = "cards"   # <- tutaj trzymaj swoje pliki .png

# ---------- Narzędzia ----------
def load_png_bytes_from_folder(folder: str):
    """Wczytaj wszystkie PNG jako bytes w kolejności alfabetycznej."""
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
        "cards_dir": DEFAULT_CARDS_DIR,
        "hand_size": 3,
    }.items():
        if k not in st.session_state: st.session_state[k] = v

def init_deck(images, image_paths):
    st.session_state.images = images
    st.session_state.image_paths = image_paths
    st.session_state.deck = list(range(len(images)))
    random.shuffle(st.session_state.deck)
    st.session_state.discard = []
    st.session_state.hand = []
    st.session_state.exhausted = False

def draw_to_hand_size():
    hand = st.session_state.hand
    deck = st.session_state.deck
    target = st.session_state.hand_size

    while len(hand) < target and deck:
        nxt = deck.pop()
        if nxt not in hand:
            hand.append(nxt)

    st.session_state.exhausted = len(hand) < target and len(deck) == 0

def counters():
    st.caption(
        f"Ręka: **{len(st.session_state.hand)}** | "
        f"W talii: **{len(st.session_state.deck)}** | "
        f"Odrzucone: **{len(st.session_state.discard)}** | "
        f"Kart w zestawie: **{len(st.session_state.images)}**"
    )

def render_hand_ui():
    hand = st.session_state.hand
    images = st.session_state.images
    size = st.session_state.hand_size

    cols = st.columns(size if size > 0 else 1, gap="small")
    for pos, idx in enumerate(hand):
        with cols[pos % max(size,1)]:
            img = Image.open(BytesIO(images[idx]))
            st.image(img, use_column_width=True)
            st.checkbox("Odrzuć tę kartę", key=f"discard_{pos}")

# ---------- Aplikacja ----------
def main():
    ensure_state()
    st.title("Karty z PNG (stałe zasoby)")

    with st.sidebar:
        st.header("Ustawienia")
        st.session_state.cards_dir = st.text_input("Folder z kartami", st.session_state.cards_dir)
        st.session_state.hand_size = st.number_input("Wielkość ręki", min_value=1, max_value=10, value=st.session_state.hand_size, step=1)
        seed = st.text_input("Seed losowania (opcjonalnie)", value="")
        col_a, col_b = st.columns(2)
        reload_clicked = col_a.button("🔄 Przeładuj karty")
        reset_clicked = col_b.button("♻️ Reset rundy")

    # Przeładowanie kart z dysku
    if reload_clicked:
        imgs, paths = load_png_bytes_from_folder(st.session_state.cards_dir)
        if not imgs:
            st.error(f"Brak plików .png w: {st.session_state.cards_dir}")
        else:
            if seed: random.seed(seed)
            init_deck(imgs, paths)
            st.success(f"Wczytano {len(imgs)} kart z '{st.session_state.cards_dir}'")

    # Reset rundy (z aktualnego zestawu)
    if reset_clicked and st.session_state.images:
        if seed: random.seed(seed)
        init_deck(st.session_state.images, st.session_state.image_paths)
        st.success("Zresetowano rundę i przetasowano talię.")

    # Auto-inicjalizacja przy pierwszym uruchomieniu (jeśli folder istnieje)
    if not st.session_state.images:
        if os.path.isdir(st.session_state.cards_dir):
            imgs, paths = load_png_bytes_from_folder(st.session_state.cards_dir)
            if imgs:
                if seed: random.seed(seed)
                init_deck(imgs, paths)
            else:
                st.info(f"Wrzuć pliki PNG do folderu '{st.session_state.cards_dir}' i kliknij „Przeładuj karty”.")
        else:
            st.info(f"Utwórz folder '{st.session_state.cards_dir}', dodaj tam swoje PNG i kliknij „Przeładuj karty” w sidebarze.")

    # Główne UI
    if st.session_state.images:
        if not st.session_state.hand:
            draw_to_hand_size()

        counters()
        render_hand_ui()
        counters()

        left, right = st.columns([1, 3])

        if left.button("Dobierz do pełnej ręki", disabled=not st.session_state.deck):
            draw_to_hand_size()
            # wyczyść zaznaczenia
            for pos in range(len(st.session_state.hand)):
                st.session_state[f"discard_{pos}"] = False

        if right.button("Odrzuć zaznaczone i dobierz"):
            # Usuwamy od końca, żeby indeksy się nie rozjechały
            for pos in range(len(st.session_state.hand) - 1, -1, -1):
                if st.session_state.get(f"discard_{pos}", False):
                    st.session_state.discard.append(st.session_state.hand.pop(pos))
                    st.session_state[f"discard_{pos}"] = False
            if st.session_state.deck:
                draw_to_hand_size()
            else:
                st.session_state.exhausted = len(st.session_state.hand) < st.session_state.hand_size

        if st.session_state.exhausted:
            st.warning("Talia się skończyła. Odrzucone karty nie wracają do puli — nowych już nie dobierzesz.")
    else:
        st.stop()

if __name__ == "__main__":
    main()
