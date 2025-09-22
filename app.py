# app.py — Dwa pokoje, dwóch graczy, niezależne talie + twist
# Wymagane: streamlit, pymupdf, pillow

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF
from io import BytesIO
import random
import threading
import os

st.set_page_config(page_title="Karty z PDF: pokoje & twist", layout="wide")
HAND_SIZE = 3
TWIST_DECKS = {
    "gyhran": [f"g{i}" for i in range(1, 7)],
    "ash":    [f"a{i}" for i in range(1, 7)],
}

# ---------- GLOBALNY "SERWER" W PAMIĘCI (współdzielony między klientami) ----------

class RoomState:
    def __init__(self, seed=None):
        self.lock = threading.Lock()
        self.seed = seed or random.randrange(1_000_000_000)
        self.rng = random.Random(self.seed)

        # Deck obrazków (bytes PNG) współdzielony przez graczy (ale talie niezależne)
        self.deck_images: list[bytes] = []
        self.deck_name: str | None = None  # nazwa/właściciel uploadu (np. plik)

        # Stan graczy (niezależne talie)
        self.players = {
            "host": {
                "deck": [],      # list[int] indeksy kart do dociągnięcia
                "hand": [],      # list[int]
                "discard": [],   # list[int]
                "exhausted": False,
            },
            "player": {
                "deck": [],
                "hand": [],
                "discard": [],
                "exhausted": False,
            },
        }

        # Twist — wspólny dla pokoju
        self.twist_choice: str | None = None               # 'gyhran' | 'ash'
        self.twist_available: list[str] = []               # np. ['g1'..'g6']
        self.twist_discard: list[str] = []
        self.twist_current: str | None = None

    def init_player_deck(self, role: str):
        """Wytasuj niezależną talię gracza z bazowej listy obrazków."""
        n = len(self.deck_images)
        idx = list(range(n))
        self.rng.shuffle(idx)
        self.players[role]["deck"] = idx
        self.players[role]["hand"] = []
        self.players[role]["discard"] = []
        self.players[role]["exhausted"] = False

    def draw_to_hand(self, role: str, hand_size: int = HAND_SIZE):
        p = self.players[role]
        while len(p["hand"]) < hand_size and p["deck"]:
            nxt = p["deck"].pop()
            if nxt not in p["hand"]:
                p["hand"].append(nxt)
        p["exhausted"] = (len(p["hand"]) < hand_size) and (len(p["deck"]) == 0)

    def discard_selected(self, role: str, positions: list[int]):
        p = self.players[role]
        for pos in sorted(positions, reverse=True):
            if 0 <= pos < len(p["hand"]):
                self.players[role]["discard"].append(p["hand"].pop(pos))
        # nie dobieramy tutaj — dobieranie jest osobnym przyciskiem

    # ----- Twist -----
    def set_twist_choice(self, choice: str):
        self.twist_choice = choice
        self.twist_available = list(TWIST_DECKS[choice])
        self.rng.shuffle(self.twist_available)
        self.twist_discard = []
        self.twist_current = None

    def draw_twist(self):
        if not self.twist_available:
            self.twist_current = None
            return None
        self.twist_current = self.twist_available.pop()
        return self.twist_current

    def change_twist(self):
        """Odrzuć aktualnego twista i losuj nowego (jeśli jest)."""
        if self.twist_current is not None:
            self.twist_discard.append(self.twist_current)
            self.twist_current = None
        return self.draw_twist()

@st.cache_resource(show_spinner=False)
def get_server():
    # dwa pokoje: room1, room2
    return {
        "room1": RoomState(),
        "room2": RoomState(),
        "twist_images_cache": {}  # np. {'g1': bytes_png, 'a1': bytes_png, ...}
    }

# ---------- Narzędzia graficzne ----------

def render_text_placeholder(label: str, w=600, h=400) -> bytes:
    """Tworzy prosty placeholder PNG z dużym napisem (używane gdy brak pliku obrazka twist)."""
    img = Image.new("RGB", (w, h), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    try:
        # font opcjonalny; Streamlit Cloud może nie mieć TTF — wtedy fallback
        font = ImageFont.truetype("arial.ttf", 120)
    except:
        font = ImageFont.load_default()
    text = label.upper()
    tw, th = draw.textsize(text, font=font)
    draw.text(((w - tw)//2, (h - th)//2), text, fill=(20, 20, 20), font=font)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def load_twist_image(label: str) -> bytes:
    """
    Próbuje załadować obraz z ./gyhran/{label}.png lub ./ash/{label}.png.
    Jeśli plik nie istnieje, zwraca placeholder z napisem.
    """
    server = get_server()
    cache = server["twist_images_cache"]
    if label in cache:
        return cache[label]

    folder = "gyhran" if label.startswith("g") else "ash"
    path_png = os.path.join(folder, f"{label}.png")
    if os.path.exists(path_png):
        with open(path_png, "rb") as f:
            data = f.read()
    else:
        data = render_text_placeholder(label)
    cache[label] = data
    return data

@st.cache_resource(show_spinner=False)
def pdf_to_images_cached(pdf_bytes: bytes, dpi: int = 144) -> list[bytes]:
    """Render PDF pages -> list of PNG bytes (cache'owane po bytes)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    imgs = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        imgs.append(pix.tobytes("png"))
    doc.close()
    return imgs

# ---------- UI pomocnicze ----------

def get_query_params_defaults():
    qp = st.query_params
    room = qp.get("room", "1")
    role = qp.get("role", "host")
    if room not in ("1", "2"):
        room = "1"
    if role not in ("host", "player"):
        role = "host"
    return room, role

def role_badge(role: str):
    return "🎮 Host" if role == "host" else "🧑‍🤝‍🧑 Gracz 2"

def room_key(room: str) -> str:
    return "room1" if room == "1" else "room2"

# ---------- Ekrany ----------

def sidebar(room: str, role: str, rs: RoomState):
    st.sidebar.header("Nawigacja")
    st.sidebar.write(f"**Pokój {room}** — {role_badge(role)}")
    # Szybkie linki
    st.sidebar.markdown(
        f"- Host P{room}:  `?room={room}&role=host`\n"
        f"- Gracz P{room}: `?room={room}&role=player}`"
    )
    st.sidebar.divider()

    # Upload talia bazowa — tylko host
    if role == "host":
        st.sidebar.subheader("Talia bazowa (PDF)")
        uploaded = st.sidebar.file_uploader("Wgraj PDF", type=["pdf"], key=f"pdf_{room}")
        if uploaded is not None:
            with rs.lock:
                imgs = pdf_to_images_cached(uploaded.read())
                if not imgs:
                    st.sidebar.error("PDF nie zawiera stron.")
                else:
                    rs.deck_images = imgs
                    rs.deck_name = uploaded.name
                    # zresetuj talie graczy
                    rs.init_player_deck("host")
                    rs.init_player_deck("player")
                    st.sidebar.success(f"Wczytano: {uploaded.name} (kart: {len(imgs)})")
    else:
        # info dla gracza
        with rs.lock:
            if rs.deck_images:
                st.sidebar.info(f"Talia gospodarza: **{rs.deck_name}** — kart: **{len(rs.deck_images)}**")
            else:
                st.sidebar.warning("Czekaj na hosta — musi wgrać PDF z talią.")

    st.sidebar.divider()
    st.sidebar.subheader("Twist (wspólny w pokoju)")
    with rs.lock:
        choice = rs.twist_choice

    if role == "host":
        new_choice = st.sidebar.radio(
            "Wybierz talię twist",
            options=["gyhran", "ash"],
            index=0 if choice is None or choice == "gyhran" else 1,
            key=f"twist_choice_{room}",
            horizontal=True
        )
        if st.sidebar.button("Ustaw / Zmień talię twist", key=f"btn_set_twist_{room}"):
            with rs.lock:
                rs.set_twist_choice(new_choice)
                rs.draw_twist()
    else:
        if choice is None:
            st.sidebar.warning("Host jeszcze nie wybrał talii twist.")
        else:
            st.sidebar.info(f"Wybrana talia twist: **{choice}**")

    with rs.lock:
        cur = rs.twist_current
        left = len(rs.twist_available)

    if cur:
        st.sidebar.image(load_twist_image(cur), caption=f"Twist: {cur}", use_column_width=True)
    else:
        st.sidebar.info("Brak aktualnej karty twist.")

    if role == "host":
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("Losuj twist", key=f"draw_twist_{room}"):
                with rs.lock:
                    rs.draw_twist()
        with col2:
            if st.button("Zmień twist", key=f"change_twist_{room}"):
                with rs.lock:
                    rs.change_twist()
        st.sidebar.caption(f"Pozostało w talii twist: **{left}**")
    else:
        st.sidebar.caption(f"Pozostało w talii twist: **{left}**")

def player_panel(title: str, role: str, rs: RoomState):
    st.subheader(title)

    with rs.lock:
        deck_ok = len(rs.deck_images) > 0
    if not deck_ok:
        st.info("Brak talii bazowej. Host musi wgrać PDF w panelu bocznym.")
        return

    # zapewnij inicjalizację talii gracza (gdy host dopiero co wgrał PDF)
    with rs.lock:
        if rs.players[role]["deck"] == [] and rs.players[role]["hand"] == [] and rs.players[role]["discard"] == []:
            rs.init_player_deck(role)

        # automatycznie dociągnij start do 3, jeśli pusta ręka
        if not rs.players[role]["hand"]:
            rs.draw_to_hand(role)

        hand = list(rs.players[role]["hand"])
        deck_len = len(rs.players[role]["deck"])
        disc_len = len(rs.players[role]["discard"])
        exhausted = rs.players[role]["exhausted"]
        deck_images = rs.deck_images[:]  # kopia referencji

    st.caption(f"Ręka: **{len(hand)}** | W talii: **{deck_len}** | Odrzucone: **{disc_len}**")

    # Wyświetl karty
    cols = st.columns(HAND_SIZE, gap="small")
    discard_flags = [False] * len(hand)
    for pos, idx in enumerate(hand):
        with cols[pos % HAND_SIZE]:
            img = Image.open(BytesIO(deck_images[idx]))
            st.image(img, use_column_width=True)
            discard_flags[pos] = st.checkbox("Odrzuć tę kartę", key=f"{role}_discard_{pos}")

    # Przyciski
    c1, c2, c3 = st.columns([1,1,2])
    with c1:
        if st.button("Odrzuć zaznaczone", key=f"{role}_btn_discard"):
            selected = []
            # odczytaj stany checkboxów
            for pos in range(len(hand)):
                if st.session_state.get(f"{role}_discard_{pos}", False):
                    selected.append(pos)
            with rs.lock:
                rs.discard_selected(role, selected)
            # wyczyść checkboxy po akcji
            for pos in range(len(hand)):
                st.session_state[f"{role}_discard_{pos}"] = False

    with c2:
        if st.button("Uzupełnij do 3", key=f"{role}_btn_draw"):
            with rs.lock:
                rs.draw_to_hand(role)

    with c3:
        if exhausted:
            st.warning("Talia się skończyła — nie da się już dociągnąć do pełnych 3 (odrzucone nie wracają).")
        else:
            st.caption("Dobieranie działa, dopóki w talii są karty.")

def main():
    server = get_server()
    room, role = get_query_params_defaults()
    rk = room_key(room)
    rs: RoomState = server[rk]

    sidebar(room, role, rs)

    st.title(f"Pokój {room} — {role_badge(role)}")

    # Ekrany graczy w dwóch kolumnach, aby łatwo porównać (obie strony widzą to samo)
    # Każdy gracz w swojej zakładce po prostu używa swojego panelu.
    left, right = st.columns(2)
    with left:
        player_panel("Gracz 1 (Host)", "host", rs)
    with right:
        player_panel("Gracz 2", "player", rs)

    # Sekcja twist (widoczna dla obu — w sidebarze widać kontrolki hosta)
    st.divider()
    st.subheader("Karta Twist (wspólna dla pokoju)")
    with rs.lock:
        cur = rs.twist_current
    if cur:
        st.image(load_twist_image(cur), caption=f"Aktualny twist: {cur}", use_column_width=True)
    else:
        st.info("Brak aktualnej karty twist (host może wylosować w panelu bocznym).")

if __name__ == "__main__":
    main()
