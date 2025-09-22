# app.py — Dwuosobowa gra: zwykłe karty z PNG + osobna pula "twist" z folderu gyhran/
# uruchom: python -m pip install streamlit pillow
#          python -m streamlit run app.py
#
# Przykładowe URL-e:
#   HOST:   http://localhost:8501/?game=demo&role=host
#   GRACZ1: http://localhost:8501/?game=demo&role=p1
#   GRACZ2: http://localhost:8501/?game=demo&role=p2
#
# Uwaga: folder "gyhran" NIE jest w "cards". To osobny folder z PNG twist (np. g1.png ... g6.png).

import streamlit as st
from PIL import Image
from io import BytesIO
import random, os, glob, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

st.set_page_config(page_title="Karty 2 graczy (PNG + Twist)", layout="wide")

DEFAULT_CARDS_DIR = "cards"     # zwykłe karty (PNG)
DEFAULT_TWIST_DIR = "gyhran"    # karty twist (PNG, np. g1.png ... g6.png)

# ---------- IO: wczytywanie PNG ----------

def load_png_bytes_from_folder(folder: str) -> tuple[list[bytes], list[str]]:
    paths = sorted(glob.glob(os.path.join(folder, "*.png")))
    imgs: list[bytes] = []
    for p in paths:
        with Image.open(p) as im:
            buf = BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
            imgs.append(buf.getvalue())
    return imgs, paths

# ---------- Globalny magazyn gier (w pamięci procesu) ----------

@dataclass
class GameState:
    # zasoby
    card_images: list[bytes] = field(default_factory=list)
    card_paths: list[str] = field(default_factory=list)

    twist_images: list[bytes] = field(default_factory=list)
    twist_paths: list[str] = field(default_factory=list)

    # ustawienia
    hand_size: int = 3
    seed: Optional[str] = None
    cards_dir: str = DEFAULT_CARDS_DIR
    twist_dir: str = DEFAULT_TWIST_DIR

    # talie / stany wspólne
    deck: list[int] = field(default_factory=list)         # indeksy zwykłych
    discard: list[int] = field(default_factory=list)      # zwykłe odrzucone
    twist_deck: list[int] = field(default_factory=list)   # indeksy twist (wspólna pula)
    twist_discard: list[int] = field(default_factory=list)

    # stany graczy
    hands: Dict[str, list[int]] = field(default_factory=lambda: {"p1": [], "p2": []})
    twist_current: Dict[str, Optional[int]] = field(default_factory=lambda: {"p1": None, "p2": None})

    # meta
    locked: threading.Lock = field(default_factory=threading.Lock)

    def reseed(self):
        if self.seed:
            random.seed(self.seed)

    def initialize_from_dirs(self):
        """Wczytaj PNG z self.cards_dir oraz self.twist_dir i zainicjalizuj talie."""
        self.reseed()
        imgs, paths = load_png_bytes_from_folder(self.cards_dir)
        timgs, tpaths = load_png_bytes_from_folder(self.twist_dir)

        if not imgs:
            raise RuntimeError(f"Brak plików PNG w folderze kart: {self.cards_dir}")
        if not timgs:
            raise RuntimeError(f"Brak plików PNG w folderze twist: {self.twist_dir}")

        self.card_images, self.card_paths = imgs, paths
        self.twist_images, self.twist_paths = timgs, tpaths

        # talie
        self.deck = list(range(len(self.card_images)))
        random.shuffle(self.deck)
        self.discard = []

        self.twist_deck = list(range(len(self.twist_images)))
        random.shuffle(self.twist_deck)
        self.twist_discard = []

        # ręce i twisty
        self.hands = {"p1": [], "p2": []}
        self.twist_current = {"p1": None, "p2": None}

    def draw_up_to_full(self, player: str):
        """Dobierz zwykłe karty do pełnej ręki (odrzucone nie wracają)."""
        with self.locked:
            target = self.hand_size
            hand = self.hands[player]
            while len(hand) < target and self.deck:
                nxt = self.deck.pop()
                if nxt not in hand:
                    hand.append(nxt)

    def discard_selected(self, player: str, to_discard: list[int]):
        """Odrzuć wskazane indeksy kart (ID kart = indeksy w card_images)."""
        with self.locked:
            hand = self.hands[player]
            for idx in to_discard:
                if idx in hand:
                    hand.remove(idx)
                    self.discard.append(idx)

    def change_twist(self, player: str):
        """Odrzuć bieżący twist gracza i dociągnij nowy z puli twist (niezależnej od zwykłej talii)."""
        with self.locked:
            # odrzuć bieżący twist (jeśli był)
            cur = self.twist_current.get(player)
            if cur is not None:
                self.twist_discard.append(cur)
                self.twist_current[player] = None
            # dobierz nowy (jeśli są w talii twist)
            if self.twist_deck:
                self.twist_current[player] = self.twist_deck.pop()
            # jeśli skończą się twist — zostaje None (brak karty twist)

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
    """Usuń z session_state flagi kart, których nie ma już ani w ręce gracza, ani w talii."""
    for k in list(st.session_state.keys()):
        if k.startswith(f"discard_card_{player}_"):
            try:
                idx = int(k.split("_")[-1])
            except ValueError:
                continue
            if idx not in alive_ids:
                st.session_state.pop(k, None)

# ---------- Aplikacja ----------

def main():
    # Parametry z URL: ?game=...&role=host|p1|p2
    qp = st.query_params  # Streamlit >= 1.32
    game_id = qp.get("game", "default")
    role    = qp.get("role", "host")
    if role not in ("host", "p1", "p2"):
        role = "host"

    st.title(f"Gra 2-osobowa — pokój **{game_id}** ({'HOST' if role=='host' else role.upper()})")
    game = get_game(game_id)

    # --- PANEL HOSTA ---
    if role == "host":
        st.sidebar.header("Ustawienia (HOST)")
        cards_dir = st.sidebar.text_input("Folder kart (PNG)", value=game.cards_dir)
        twist_dir = st.sidebar.text_input("Folder twist (PNG)", value=game.twist_dir)
        hand_size = st.sidebar.number_input("Wielkość ręki", 1, 10, game.hand_size, 1)
        seed = st.sidebar.text_input("Seed (opcjonalnie)", value=game.seed or "")
        col1, col2 = st.sidebar.columns(2)
        reload_clicked = col1.button("🔄 Załaduj z dysku")
        reset_clicked  = col2.button("♻️ Reset rundy")
        st.sidebar.caption("Po załadowaniu/resetcie gracze zobaczą zmiany.")

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
                st.success("Zresetowano rundę (tasowanie talii).")
            except Exception as e:
                st.error(str(e))

        st.subheader("Szybkie linki dla graczy")
        st.markdown(
            f"""
- [Host (ten widok)](?game={game_id}&role=host)  
- [Gracz 1](?game={game_id}&role=p1)  
- [Gracz 2](?game={game_id}&role=p2)
""",
            unsafe_allow_html=False
        )

        st.divider()
        st.subheader("Podgląd zasobów")
        st.write(f"Kart zwykłych: **{len(game.card_images)}**  |  Twist: **{len(game.twist_images)}**")
        st.write(f"Talia: {len(game.deck)} | Odrzucone: {len(game.discard)}")
        st.write(f"Twist talia: {len(game.twist_deck)} | Twist odrzucone: {len(game.twist_discard)}")
        st.write(f"Ręka P1: {len(game.hands['p1'])} | Ręka P2: {len(game.hands['p2'])}")
        st.write(f"Twist P1: {game.twist_current['p1']} | Twist P2: {game.twist_current['p2']}")
        st.info("Otwórz linki p1/p2 w nowych kartach, aby zobaczyć widoki graczy.")

    # --- WIDOK GRACZA ---
    else:
        # jeśli host jeszcze nie zainicjalizował, spróbuj z domyślnych folderów
        if not game.card_images or not game.twist_images:
            try:
                with game.locked:
                    game.initialize_from_dirs()
            except Exception as e:
                st.error(f"Host nie załadował kart, a pod domyślnymi ścieżkami ich brak.\nSzczegóły: {e}")
                st.stop()

        # Start: dociągnij do pełnej ręki
        if len(game.hands[role]) < game.hand_size:
            game.draw_up_to_full(role)

        # Start: jeśli brak karty twist dla gracza – dociągnij jedną
        if game.twist_current[role] is None and game.twist_deck:
            game.change_twist(role)

        # Stan nagłówkowy
        st.caption(
            f"Ręka: **{len(game.hands[role])}/{game.hand_size}** | "
            f"Wspólna talia: **{len(game.deck)}** | "
            f"Twist: {'brak' if game.twist_current[role] is None else 'jest'} | "
            f"Pozostałe twist: **{len(game.twist_deck)}**"
        )

        cols_top = st.columns([2, 1])

        # --- RĘKA GRACZA ---
        with cols_top[0]:
            st.subheader("Twoja ręka")
            cols = st.columns(max(game.hand_size, 1), gap="small")
            # żywe ID do czyszczenia starych checkboxów
            alive_ids = set(game.hands[role]) | set(game.deck)

            for pos, idx in enumerate(game.hands[role]):
                with cols[pos % max(game.hand_size, 1)]:
                    show_image(game.card_images[idx])
                    st.checkbox("Odrzuć tę kartę", key=discard_key(role, idx))

            clear_obsolete_flags(role, alive_ids)

            c1, c2 = st.columns([1, 1])
            # Odrzuć zaznaczone (bez dobierania)
            if c1.button("Odrzuć zaznaczone"):
                selected = [idx for idx in list(game.hands[role]) if st.session_state.get(discard_key(role, idx), False)]
                if selected:
                    game.discard_selected(role, selected)
                    for idx in selected:
                        st.session_state.pop(discard_key(role, idx), None)
                else:
                    st.info("Nie zaznaczono żadnej karty.")

            # Dobierz do pełnej ręki
            if c2.button(
                "Dobierz do pełnej ręki",
                disabled=(len(game.deck) == 0 or len(game.hands[role]) >= game.hand_size)
            ):
                game.draw_up_to_full(role)

        # --- TWIST GRACZA ---
        with cols_top[1]:
            st.subheader("Twist")
            cur = game.twist_current[role]
            if cur is not None:
                show_image(game.twist_images[cur])
            else:
                st.info("Brak karty twist.")

            if st.button(
                "Zmień kartę twist",
                disabled=(len(game.twist_deck) == 0 and cur is None)
            ):
                game.change_twist(role)
                if game.twist_current[role] is None:
                    st.warning("Skończyły się karty twist.")

        st.divider()
        st.caption("Odrzucone (zwykłe i twist) nie wracają do puli. Reset/ustawienia po stronie HOSTA.")

if __name__ == "__main__":
    main()
