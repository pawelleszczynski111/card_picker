# app.py — Karty z PNG (stabilne klucze checkboxów po ID karty)
# uruchom: python -m pip install streamlit pillow
#          python -m streamlit run app.py

import streamlit as st
from PIL import Image
from io import BytesIO
import random, os, glob

st.set_page_config(page_title="Karty z PNG", layout="wide")
DEFAULT_CARDS_DIR = "cards"

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
        "cards_dir": DEFAULT_CARDS_DIR,
        "hand_size": 3,
    }.items():
        if k not in st.session_state: st.session_state[k] = v

def init_deck(images, image_paths, seed=None):
    if seed: random.seed(seed)
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
    target = st.session_state.hand_size
    while len(hand) < target and deck:
        nxt = deck.pop()
        if nxt not in hand:
            hand.append(nxt)
    st.session_state.exhausted = len(hand) < target and len(deck) == 0
    clear_obsolete_discard_flags()  # utrzymuj porządek flag

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
    to_del = [k for k in st.session_state.keys()
              if k.startswith("discard_card_")
              and (int(k.split("_")[-1]) not in alive)]
    for k in to_del:
        st.session_state.pop(k, None)

def clear_all_discard_flags():
    for k in [k for k in st.session_state.keys() if k.startswith("discard_card_")]:
        st.session_state.pop(k, None)

def render_hand_ui():
    hand = st.session_state.hand
    images = st.session_state.images
    size = st.session_state.hand_size
    cols = st.columns(max(size, 1), gap="small")

    for pos, idx in enumerate(hand):
        with cols[pos % max(size, 1)]:
            img = Image.open(BytesIO(images[idx]))
            st.image(img, use_column_width=True)
            # CHECKBOX ma klucz po ID karty, nie po pozycji
            st.checkbox("Odrzuć tę kartę", key=discard_key(idx))

# ---------- App ----------
def main():
    ensure_state()
    st.title("Karty z PNG (stabilne klucze)")

    with st.sidebar:
        st.header("Ustawienia")
        st.session_state.cards_dir = st.text_input("Folder z kartami", st.session_state.cards_dir)
        st.session_state.hand_size = st.number_input("Wielkość ręki", 1, 10, st.session_state.hand_size, 1)
        seed = st.text_input("Seed losowania (opcjonalnie)", value="")
        col_a, col_b = st.columns(2)
        reload_clicked = col_a.button("🔄 Przeładuj karty")
        reset_clicked = col_b.button("♻️ Reset rundy")

    if reload_clicked:
        imgs, paths = load_png_bytes_from_folder(st.session_state.cards_dir)
        if not imgs:
            st.error(f"Brak plików .png w: {st.session_state.cards_dir}")
        else:
            init_deck(imgs, paths, seed or None)
            st.success(f"Wczytano {len(imgs)} kart z '{st.session_state.cards_dir}'")

    if reset_clicked and st.session_state.images:
        init_deck(st.session_state.images, st.session_state.image_paths, seed or None)
        st.success("Zresetowano rundę i przetasowano talię.")

    # Auto-init
    if not st.session_state.images:
        if os.path.isdir(st.session_state.cards_dir):
            imgs, paths = load_png_bytes_from_folder(st.session_state.cards_dir)
            if imgs:
                init_deck(imgs, paths, seed or None)
            else:
                st.info(f"Wrzuć PNG do '{st.session_state.cards_dir}' i kliknij „Przeładuj karty”.")
        else:
            st.info(f"Utwórz folder '{st.session_state.cards_dir}', dodaj PNG i kliknij „Przeładuj karty” w sidebarze.")

    if not st.session_state.images:
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
        # iterujemy po KOPII listy, żeby bezpiecznie modyfikować hand
        for idx in list(st.session_state.hand):
            if st.session_state.get(discard_key(idx), False):
                st.session_state.hand.remove(idx)
                st.session_state.discard.append(idx)
                # usuń flagę tego checkboxa – karta znika z UI
                st.session_state.pop(discard_key(idx), None)
                removed_any = True
        if not removed_any:
            st.info("Nie zaznaczono żadnej karty do odrzucenia.")
        st.session_state.exhausted = (
            len(st.session_state.hand) < st.session_state.hand_size
            and len(st.session_state.deck) == 0
        )

    # 2) Dobierz do pełnej ręki
    if right.button("Dobierz do pełnej ręki", disabled=not st.session_state.deck):
        draw_to_hand_size()
        # po dociągnięciu nie trzeba nic resetować — klucze są po ID karty

    if st.session_state.exhausted:
        st.warning("Talia się skończyła. Odrzucone karty nie wracają do puli — nowych już nie dobierzesz.")

if __name__ == "__main__":
    main()
