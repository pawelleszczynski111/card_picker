# app.py — Karty z PDF (odrzucone NIE wracają do puli)
# Wymagane pakiety: streamlit, pymupdf, pillow

import streamlit as st
from PIL import Image
import fitz  # PyMuPDF
from io import BytesIO
import random

# --- USTAWIENIA ---
HAND_SIZE = 3  # rozmiar ręki (3 karty)

st.set_page_config(page_title="Karty z PDF", layout="wide")

# --- NARZĘDZIA ---

@st.cache_resource(show_spinner=False)
def load_pdf_to_images(pdf_bytes: bytes, dpi: int = 144):
    """
    Renderuje strony PDF do listy obrazów PNG (bytes).
    Cache'owane na bazie bytes, więc ponowne wgranie tego samego pliku nie renderuje na nowo.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    imgs = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        imgs.append(pix.tobytes("png"))
    doc.close()
    return imgs

def ensure_state():
    defaults = {
        "images": [],      # list[bytes] — obrazki kart
        "deck": [],        # list[int] — indeksy kart w talii (do dociągnięcia)
        "discard": [],     # list[int] — indeksy kart odrzuconych (NIE wracają)
        "hand": [],        # list[int] — aktualna ręka
        "file_name": None, # nazwa wgranego pliku
        "exhausted": False # flaga: talia wyczerpana i nie da się dociągać do pełnych 3
    }
    for k, v in defaults.items():
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

def reset_round():
    """Reset rundy na podstawie aktualnie wgranego PDF-a."""
    if st.session_state.images:
        init_deck(st.session_state.images, st.session_state.file_name)

def draw_to_three():
    """
    Dobiera karty z 'deck' do osiągnięcia HAND_SIZE.
    ODRZUCONE NIE WRACAJĄ: nie sięgamy do discard — jeśli deck pusty, kończymy.
    """
    hand = st.session_state.hand
    deck = st.session_state.deck

    while len(hand) < HAND_SIZE and deck:
        nxt = deck.pop()
        if nxt not in hand:
            hand.append(nxt)

    # Jeśli nie udało się uzupełnić do pełnej ręki i talia pusta — oznacz koniec
    st.session_state.exhausted = (len(hand) < HAND_SIZE) and (len(deck) == 0)

def counters():
    hand_n = len(st.session_state.hand)
    deck_n = len(st.session_state.deck)
    discard_n = len(st.session_state.discard)
    st.caption(f"Ręka: **{hand_n}** | W talii: **{deck_n}** | Odrzucone: **{discard_n}**")

def render_hand_and_discard_ui():
    hand = st.session_state.hand
    images = st.session_state.images

    # Pokazuj karty w kolumnach (do 3)
    cols = st.columns(max(1, HAND_SIZE), gap="small")

    # Tworzymy checkbox dla każdej karty w ręce
    for pos, idx in enumerate(hand):
        with cols[pos % HAND_SIZE]:
            img = Image.open(BytesIO(images[idx]))
            st.image(img, use_column_width=True)
            st.checkbox("Odrzuć tę kartę", key=f"discard_{pos}", value=False)

    # Przyciski akcji
    left, mid, right = st.columns([1, 1, 2])

    with left:
        st.button(
            "Dobierz do 3",
            disabled=(not st.session_state.deck),
            on_click=draw_to_three
        )

    def discard_and_draw():
        # Zbierz zaznaczone checkboxy i odrzuć od końca, by nie psuć indeksów
        for pos in range(len(st.session_state.hand) - 1, -1, -1):
            if st.session_state.get(f"discard_{pos}", False):
                st.session_state.discard.append(st.session_state.hand.pop(pos))
        # Wyczyść checkboxy (mogą zostać „sierotami” po zmianie ręki)
        for k in list(st.session_state.keys()):
            if k.startswith("discard_"):
                st.session_state[k] = False
        # Spróbuj dobrać, jeśli talia nie jest pusta
        if st.session_state.deck:
            draw_to_three()
        else:
            st.session_state.exhausted = len(st.session_state.hand) < HAND_SIZE

    with mid:
        st.button("Odrzuć zaznaczone i dobierz", on_click=discard_and_draw)

    with right:
        st.button("🔄 Reset rundy", on_click=reset_round, help="Tasuje całą talię od nowa (ten sam PDF).")

    # Komunikat o wyczerpaniu talii
    if st.session_state.exhausted:
        st.warning("Talia się skończyła. Odrzucone karty nie wracają do puli, więc nie da się już dobrać nowych.")

# --- APLIKACJA ---

def main():
    ensure_state()

    st.title("Karty z PDF (odrzucone nie wracają)")
    st.write("Wgraj PDF — każda strona to karta. Aplikacja dobiera do 3 kart, "
             "pozwala odrzucać dowolną liczbę i dobierać dalej. Odrzucone karty **nie wracają** do puli.")

    with st.sidebar:
        st.header("Plik PDF")
        uploaded = st.file_uploader("Wgraj PDF", type=["pdf"])
        st.markdown("---")
        st.caption("Wskazówka: jeśli wgrasz ten sam PDF ponownie, render będzie użyty z cache.")

    # Obsługa nowego uploadu
    if uploaded is not None:
        new_file = (uploaded.name != st.session_state.get("file_name"))
        if new_file:
            with st.spinner("Renderuję PDF…"):
                imgs = load_pdf_to_images(uploaded.read())
            if not imgs:
                st.error("PDF nie zawiera stron.")
                return
            init_deck(imgs, uploaded.name)
            st.success(f"Wczytano: **{uploaded.name}** — liczba kart: **{len(imgs)}**")

    # Główna logika ekranu
    if st.session_state.images:
        # Pierwsze automatyczne dobranie do 3 po wgraniu
        if not st.session_state.hand:
            draw_to_three()

        counters()
        render_hand_and_discard_ui()
        counters()
    else:
        st.info("Najpierw wgraj plik PDF w panelu po lewej.")

if __name__ == "__main__":
    main()
