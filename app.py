# app.py — Streamlit "karty z PDF" (odrzucone karty NIE wracają do talii)
# pip install streamlit pymupdf pillow

import streamlit as st
from PIL import Image
import fitz  # PyMuPDF
from io import BytesIO
import random

st.set_page_config(page_title="Karty z PDF", layout="wide")

HAND_SIZE = 3

def load_pdf_to_images(pdf_bytes: bytes, dpi: int = 144):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    imgs = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        imgs.append(pix.tobytes("png"))
    doc.close()
    return imgs

def ensure_state():
    for k, v in {
        "images": [],
        "deck": [],
        "discard": [],
        "hand": [],
        "file_name": None,
        "exhausted": False,   # <-- flaga: talia wyczerpana
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

def init_deck(images, file_name):
    st.session_state.images = images
    st.session_state.file_name = file_name
    st.session_state.deck = list(range(len(images)))
    random.shuffle(st.session_state.deck)
    st.session_state.discard = []
    st.session_state.hand = []
    st.session_state.exhausted = False

def draw_to_three():
    """
    Dobiera karty z 'deck' do osiągnięcia HAND_SIZE.
    ZMIANA: jeśli talia się skończy, NIE sięgamy do discard — po prostu kończymy.
    """
    hand = st.session_state.hand
    deck = st.session_state.deck

    while len(hand) < HAND_SIZE and deck:
        nxt = deck.pop()
        if nxt not in hand:
            hand.append(nxt)

    # Jeśli nie udało się uzupełnić do pełnej ręki i talia pusta — oznacz koniec
    st.session_state.exhausted = len(hand) < HAND_SIZE and len(deck) == 0

def render_hand_and_discard_ui():
    hand = st.session_state.hand
    images = st.session_state.images

    cols = st.columns(HAND_SIZE, gap="small")
    discard_flags = [False] * len(hand)

    for pos, idx in enumerate(hand):
        with cols[pos % HAND_SIZE]:
            img = Image.open(BytesIO(images[idx]))
            st.image(img, use_column_width=True)
            discard_flags[pos] = st.checkbox("Odrzuć tę kartę", key=f"discard_{pos}")

    left, right = st.columns([1, 3])

    # Przyciski: dobieranie działa tylko jeśli talia nie jest pusta
    if left.button("Dobierz do 3", disabled=not st.session_state.deck):
        draw_to_three()
        # reset checkboxów
        for pos in range(len(hand)):
            st.session_state[f"discard_{pos}"] = False

    if right.button("Odrzuć zaznaczone i dobierz"):
        # usuwamy od końca, by nie popsuć indeksów
        for pos in range(len(hand) - 1, -1, -1):
            if st.session_state.get(f"discard_{pos}", False):
                st.session_state.discard.append(hand.pop(pos))
                st.session_state[f"discard_{pos}"] = False
        # po odrzuceniu próbujemy dobrać — jeśli talia pusta, ręka może być < HAND_SIZE
        if st.session_state.deck:
            draw_to_three()
        else:
            st.session_state.exhausted = len(st.session_state.hand) < HAND_SIZE

    # Komunikaty stanu
    if st.session_state.exhausted:
        st.warning("Talia się skończyła. Odrzucone karty nie wracają do puli, więc nie da się już dobrać nowych.")

def counters():
    hand = len(st.session_state.hand)
    deck = len(st.session_state.deck)
    discard = len(st.session_state.discard)
    st.caption(f"Ręka: **{hand}** | W talii: **{deck}** | Odrzucone: **{discard}**")

def main():
    ensure_state()
    st.title("Karty z PDF (odrzucone nie wracają)")
    st.write("Wgraj PDF, każda strona to karta. Losuj 3, odrzucaj, dobieraj (bez powrotu odrzuconych).")

    uploaded = st.file_uploader("Wgraj PDF", type=["pdf"])
    if uploaded is not None and uploaded.name != st.session_state.get("file_name"):
        with st.spinner("Renderuję PDF…"):
            imgs = load_pdf_to_images(uploaded.read())
        if not imgs:
            st.error("PDF nie zawiera stron.")
            return
        init_deck(imgs, uploaded.name)
        st.success(f"Wczytano: {uploaded.name} — kart: {len(imgs)}")

    if st.session_state.images:
        if not st.session_state.hand:  # pierwsze dociągnięcie
            draw_to_three()
        counters()
        render_hand_and_discard_ui()
        counters()
    else:
        st.info("Najpierw wgraj PDF 👆")

if __name__ == "__main__":
    main()
