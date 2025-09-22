# app.py — 2 graczy: p1 = HOST, dwie identyczne (ale oddzielne) talie, WSPÓLNY twist
# uruchom: python -m pip install streamlit pillow
#          python -m streamlit run app.py
#
# Foldery:
#   cards/  -> zwykłe karty PNG (identyczny zestaw dla obu graczy)
#   gyhran/ -> karty twist PNG (np. g1.png...g6.png) — WSPÓLNA pula twist
#
# URL-e:
#   P1 (HOST): http://localhost:8501/?game=demo&role=p1
#   P2:        http://localhost:8501/?game=demo&role=p2

import streamlit as st
from PIL import Image
from io import BytesIO
import random, os, glob, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

st.set_page_config(page_title="Karty (2 graczy, wspólny twist)", layout="wide")

DEFAULT_CARDS_DIR = "cards"
DEFAULT_TWIST_DIR = "gyhran"

# ---------- IO: wczytywanie PNG ----------

def load_png_bytes_from_folder(folder: str) -> Tuple[List[bytes], List[str]]:
    paths = sorted(glob.glob(os.path.join(folder, "*.png")))
    imgs: List[bytes] = []
    for p in paths:
        with Image.open(p) as im:
            buf = BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
            imgs.append(buf.getvalue())
    return imgs, paths

# ---------- Pomoc: query params zgodne wstecznie ----------

def get_query_params() -> Dict[str, List[str]]:
    # Streamlit >= 1.32: st.query_params (Mapping[str,str])
    # starsze: st.experimental_get_query_params() -> Dict[str, List[str]]
    try:
        qp = st.query_params
        if isinstance(qp, dict):
            # zamień na listy dla zgodności
            return {k: [v] if not isinstance(v, list) else v for k, v in qp.items()}
        return {}
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}

def qp_get(qp: Dict[str, List[str]], key: str, default: str) -> str:
    vals = qp.get(key, [])
    if not vals:
        return default
    return vals[0]

# ---------- Globalny magazyn gier (w pamięci procesu) ----------

@dataclass
class GameState:
    # zasoby
    card_images: List[bytes] = field(default_factory=list)
    card_paths: List[str] = field(default_factory=list)

    twist_images: List[bytes] = field(default_factory=list)
    twist_paths: List[str] = field(default_factory=list)

    # ustawienia
    hand_size: int = 3
    seed: Optional[str] = None
    cards_dir: str = DEFAULT_CARDS_DIR
    twist_dir: str = DEFAULT_TWIST_DIR

    # talie / stany — OSOBNE dla p1 i p2 (identyczny układ na starcie)
    deck_p1: List[int] = field(default_factory=list)
    deck_p2: List[int] = field(default_factory=list)
    discard_p1: List[int] = field(default_factory=list)
    discard_p2: List[int] = field(default_factory=list)
    hand_p1: List[int] = field(default_factory=list)
    hand_p2: List[int] = field(default_factory=list)

    # TWIST — WSPÓLNY
    twist_deck: List[int] = field(default_factory=list)     # wspólna talia twist
    twist_discard: List[int] = field(default_factory=list)  # wspólny odrzut twist
    twist_current: Optional[int] = None                     # wspólna bieżąca karta twist

    # meta
    locked: threading.Lock = field(default_factory=threading.Lock)

    # --- logika inicjalizacji ---
    def reseed(self):
        if self.seed:
            random.seed(self.seed)

    def initialize_from_dirs(self):
        """Wczytaj PNG i zainicjalizuj DWIE IDENTYCZNE talie + WSPÓLNY twist."""
        self.reseed()
        imgs, paths = load_png_bytes_from_folder(self.cards_dir)
        timgs, tpaths = load_png_bytes_from_folder(self.twist_dir)

        if not imgs:
            raise RuntimeError(f"Brak plików PNG w folderze kart: {self.cards_dir}")
        if not timgs:
            raise RuntimeError(f"Brak plików PNG w folderze twist: {self.twist_dir}")

        self.card_images, self.card_paths = imgs, paths
        self.twist_images, self.twist_paths = timgs, tpaths

        base_order = list(range(len(self.card_images)))
        random.shuffle(base_order)          # JEDEN układ bazowy
        self.deck_p1 = base_order.copy()    # identyczne talie
        self.deck_p2 = base_order.copy()

        self.discard_p1, self.discard_p2 = [], []
        self.hand_p1, self.hand_p2 = [], []

        # twist
        self.twist_deck = list(range(len(self.twist_images)))
        random.shuffle(self.twist_deck)
        self.twist_discard = []
        self.twist_current = None  # dobierzemy przy wejściu gracza

    # --- operacje na rękach ---
    def draw_up_to_full(self, player: str):
        """Dobierz zwykłe karty do pełnej ręki gracza (odrzucone nie wracają)."""
        with self.locked:
            target = self.hand_size
            if player == "p1":
                hand, deck = self.hand_p1, self.deck_p1
            else:
                hand, deck = self.hand_p2, self.deck_p2

            while len(hand) < target and deck:
                nxt = deck.pop()
                if nxt not in hand:
                    hand.append(nxt)

    def discard_selected(self, player: str, to_discard: List[int]):
        """Odrzuć wskazane indeksy kart gracza (ID = indeksy w card_images)."""
        with self.locked:
            if player == "p1":
                hand, discard = self.hand_p1, self.discard_p1
            else:
                hand, discard = self.hand_p2, self.discard_p2
            for idx in to_discard:
                if idx in hand:
                    hand.remove(idx)
                    discard.append(idx)

    # --- TWIST (WSPÓLNY) ---
    def ensure_twist_exists(self):
        """Jeśli nie ma bieżącej karty twist, a talia twist nie jest pusta — dobierz jedną (wspólną)."""
        with self.locked:
            if self.twist_current is None and self.twist_deck:
                self.twist_current = self.twist_deck.pop()

    def change_twist(self, requester: str):
        """Zmiana twistu — dozwolona TYLKO dla p1 (host)."""
        if requester != "p1":
            return  # ignoruj żądanie p2
        with self.locked:
            if self.twist_current is not None:
                self.twist_discard.append(self.twist_current)
                self.twist_current = None
            if self.twist_deck:
                self.twist_current = self.twist_deck.pop()
            # jeśli brak w talii twist — pozostanie None

@st.cache_resource
def get_store() -> Dict[str, GameState]:
    return {}

def get_game(game_id: str) -> GameState:
    store = get_store()
    if game_id not in store:
        store[game_id] = GameState()
    return store[game_id]

# ---------- Pomocnicze UI ----------

def show_image(img_bytes: bytes, caption: Optional[str] = None):
    im = Image.open(BytesIO(img_bytes))
    st.image(im, use_column_width=True, caption=caption)

def discard_key(player: str, idx: int) -> str:
    # stabilny klucz checkboxa po ID karty i graczu
    return f"discard_card_{player}_{idx}"

def clear_obsolete_flags(player: str, alive_ids: set[int]):
    """Usuń z session_state flagi kart, których już nie ma ani w ręce gracza, ani w jego talii."""
    for k in list(st.session_state.keys()):
        prefix = f"discard_card_{player}_"
        if k.startswith(prefix):
            try:
                idx = int(k.split("_")[-1])
            except ValueError:
                continue
            if idx not in alive_ids:
                st.session_state.pop(k, None)

# ---------- Aplikacja ----------

def main():
    # Parametry z URL: ?game=...&role=p1|p2 (p1 = host)
    qp = get_query_params()
    game_id = qp_get(qp, "game", "default")
    role    = qp_get(qp, "role", "p1")
    if role not in ("p1", "p2"):  # hostem ZAWSZE jest p1
        role = "p1"

    st.title(f"Gra 2-osobowa — pokój **{game_id}** ({role.upper()}{' = HOST' if role=='p1' else ''})")
    game = get_game(game_id)

    # --- PANEL HOSTA (tylko p1) ---
    if role == "p1":
        st.sidebar.header("Ustawienia (HOST = p1)")
        cards_dir = st.sidebar.text_input("Folder kart (PNG)", value=game.cards_dir)
        twist_dir = st.sidebar.text_input("Folder twist (PNG)", value=game.twist_dir)
        hand_size = st.sidebar.number_input("Wielkość ręki", 1, 10, game.hand_size, 1)
        seed = st.sidebar.text_input("Seed (opcjonalnie)", value=game.seed or "")
        col1, col2 = st.sidebar.columns(2)
        reload_clicked = col1.button("🔄 Załaduj z dysku")
        reset_clicked  = col2.button("♻️ Reset rundy")
        st.sidebar.caption("Reset odtwarza DWIE IDENTYCZNE talie i WSPÓLNY twist od nowa.")

        if reload_clicked:
            try:
                with game.locked:
                    game.cards_dir = cards_dir
                    game.twist_dir = twist_dir
                    game.hand_size = hand_size
                    game.seed = seed or None
                    game.initialize_from_dirs()
                st.success("Załadowano zasoby i zainicjowano grę.")
            except Exception as e:
                st.error(str(e))

        if reset_clicked:
            try:
                with game.locked:
                    game.hand_size = hand_size
                    game.seed = seed or None
                    game.initialize_from_dirs()
                st.success("Zresetowano rundę (tasowanie talii + wspólny twist).")
            except Exception as e:
                st.error(str(e))

        st.subheader("Szybkie linki")
        st.markdown(
            f"""
- [Widok p1 (host)](?game={game_id}&role=p1)  
- [Widok p2](?game={game_id}&role=p2)
""",
            unsafe_allow_html=False
        )

    # --- WIDOK GRACZA (p1 i p2) ---
    # (jeśli host jeszcze nie zainicjalizował, spróbuj z domyślnych folderów)
    if not game.card_images or not game.twist_images:
        try:
            with game.locked:
                game.initialize_from_dirs()
        except Exception as e:
            st.error(f"Brak zainicjalizowanych zasobów.\nSzczegóły: {e}")
            st.stop()

    # Start: dobierz do pełnej ręki dla aktywnego gracza
    if role == "p1":
        if len(game.hand_p1) < game.hand_size:
            game.draw_up_to_full("p1")
    else:
        if len(game.hand_p2) < game.hand_size:
            game.draw_up_to_full("p2")

    # Start: zapewnij wspólny twist (jeśli brak)
    game.ensure_twist_exists()

    # Stan nagłówkowy
    deck_len = len(game.deck_p1) if role == "p1" else len(game.deck_p2)
    hand_len = len(game.hand_p1) if role == "p1" else len(game.hand_p2)
    st.caption(
        f"Twoja ręka: **{hand_len}/{game.hand_size}** | "
        f"Twoja talia: **{deck_len}** | "
        f"Wspólna pula twist: **{len(game.twist_deck)}** | "
        f"Aktualny twist: {'brak' if game.twist_current is None else 'jest'}"
    )

    cols_top = st.columns([2, 1])

    # --- RĘKA GRACZA ---
    with cols_top[0]:
        st.subheader("Twoja ręka")
        cols = st.columns(max(game.hand_size, 1), gap="small")

        if role == "p1":
            hand = game.hand_p1
            deck = game.deck_p1
            discard_list = game.discard_p1
        else:
            hand = game.hand_p2
            deck = game.deck_p2
            discard_list = game.discard_p2

        alive_ids = set(hand) | set(deck)  # do czyszczenia checkboxów

        for pos, idx in enumerate(hand):
            with cols[pos % max(game.hand_size, 1)]:
                show_image(game.card_images[idx])
                st.checkbox("Odrzuć tę kartę", key=discard_key(role, idx))

        clear_obsolete_flags(role, alive_ids)

        c1, c2 = st.columns([1, 1])
        # Odrzuć zaznaczone (bez dobierania)
        if c1.button("Odrzuć zaznaczone"):
            selected = [idx for idx in list(hand) if st.session_state.get(discard_key(role, idx), False)]
            if selected:
                game.discard_selected(role, selected)
                for idx in selected:
                    st.session_state.pop(discard_key(role, idx), None)
            else:
                st.info("Nie zaznaczono żadnej karty.")
        # Dobierz do pełnej ręki
        if c2.button(
            "Dobierz do pełnej ręki",
            disabled=(len(deck) == 0 or len(hand) >= game.hand_size)
        ):
            game.draw_up_to_full(role)

    # --- TWIST (WSPÓLNY) ---
    with cols_top[1]:
        st.subheader("Twist (wspólny)")
        if game.twist_current is not None:
            show_image(game.twist_images[game.twist_current])
        else:
            st.info("Brak karty twist (pula wyczerpana).")

        # Zmienić twist może tylko p1 (host); p2 ma wyłączony przycisk
        can_change = (role == "p1") and (len(game.twist_deck) > 0 or game.twist_current is not None)
        if st.button("Zmień kartę twist (tylko p1)", disabled=not can_change):
            game.change_twist(requester=role)
            if game.twist_current is None:
                st.warning("Skończyły się karty twist.")

    st.divider()
    st.caption("Odrzucone (zwykłe i twist) nie wracają do puli. Hostem jest zawsze p1; każda talia jest osobna, ale identyczna na starcie.")

if __name__ == "__main__":
    main()
