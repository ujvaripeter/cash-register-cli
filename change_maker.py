#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kassza & Visszajáró – egyszerűsített (aprót egyben kezeljük)
- Bankjegyek/címletek darabszám szerint: 20000, 10000, 5000, 2000, 1000, 500, 200
- Apró (100, 50, 20, 10, 5) összegben, egyetlen "apró" mező
- Tender formátumok:
    "2000"                -> 2000x1
    "2000x1, 1000x1"     -> címletek
    "2000:1;apro:150"    -> címletek + apró (összeg)
- Visszajáró: előbb nagy címletek korlátosan, maradék apróból (ha elég és /5 maradék=0)

Futtatás:
    python change_maker.py
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple
from copy import deepcopy
from datetime import date

# Napi mentés/betöltés
from storage import load_state as storage_load_state, save_state as storage_save_state, reset_state as storage_reset_state

# Megtartjuk a nagyobb címleteket önállóan:
NOTE_DENOMS = [20000, 10000, 5000, 2000, 1000, 500, 200]  # darabszám szerint
# Az aprót (100,50,20,10,5) egyetlen összegként kezeljük:
COIN_MIN_UNIT = 5  # HUF legkisebb érme
# Régi, egyfájlos mentés helye (meghagyjuk kompatibilitásból, de már nem használjuk)
SAVE_PATH = Path("drawer_state.json")

ParseError = ValueError

# Folyamatban lévő tranzakció előtti pillanatkép (snapshot)
_tx_state: Optional[Dict] = None

# Tranzakciós napló (JSONL) elérési útja: data/YYYY-MM-DD_txlog.jsonl
def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _txlog_path(day: Optional[str] = None) -> Path:
    if day is None:
        day = _today_str()
    p = Path("data")
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{day}_txlog.jsonl"


def append_txlog(entry: Dict, day: Optional[str] = None) -> None:
    path = _txlog_path(day)
    line = json.dumps(entry, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_last_tx(day: Optional[str] = None) -> Optional[Dict]:
    path = _txlog_path(day)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for ln in reversed(lines):
        if ln.strip():
            try:
                return json.loads(ln)
            except Exception:
                return None
    return None


def truncate_last_tx(day: Optional[str] = None) -> None:
    path = _txlog_path(day)
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    # töröljük az utolsó nem üres sort
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0:
        return
    new_lines = lines[:i]
    path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")


def parse_tender(text: str) -> Tuple[Dict[int, int], int]:
    """
    Visszaad: (notes_breakdown: denom->count, apro_amount:int)
    Támogatott bemenetek:
      - "2000"                -> 2000x1
      - "2000x1, 1000x1"
      - "2000:1;1000:1"
      - "apro:120" vagy "apró:120" -> apró összeg forintban
      - Kombinálható: "2000x1, 1000x1, apro:150"

    Figyelem: csak 200 Ft-tól felfelé számoljuk darabra.
              100/50/20/10/5 a 'apró' összegbe megy.
    """
    text = text.strip()
    if not text:
        return {}, 0

    # Ha puszta szám, értelmezzük x1-ként
    if re.fullmatch(r"\d+", text):
        val = int(text)
        if val in NOTE_DENOMS:
            return {val: 1}, 0
        # ha nem ismert nagy címlet, akkor tekintsük aprónak (ritka, de legyen egyszerű)
        return {}, val

    t = text.replace(";", ",").replace("×", "x").replace("X", "x").lower()
    parts = [p.strip() for p in t.split(",") if p.strip()]

    notes: Dict[int, int] = {}
    apro = 0
    for p in parts:
        # apro:NNN (apró megadása összegben)
        m_apro = re.match(r"^(ap( |)ro|apró|apro)\s*[:x]\s*(\d+)\s*$", p)
        if m_apro:
            apro += int(m_apro.group(3))
            continue

        # klasszikus: denom x count vagy denom:count
        m = re.match(r"^\s*(\d+)\s*[x:]\s*(\d+)\s*$", p)
        if not m:
            raise ParseError(f"Nem értelmezhető elem: {p!r}. Pl.: 2000x1, 1000x1, apro:150")

        denom = int(m.group(1))
        cnt = int(m.group(2))
        if cnt < 0:
            raise ParseError("Darabszám nem lehet negatív.")

        if denom in NOTE_DENOMS:
            notes[denom] = notes.get(denom, 0) + cnt
        else:
            # 100/50/20/10/5 -> apró összeg
            apro += denom * cnt

    return notes, apro


@dataclass
class Drawer:
    notes: Dict[int, int] = field(default_factory=lambda: {d: 0 for d in NOTE_DENOMS})
    apro: int = 0  # apró összege Ft

    def total(self) -> int:
        return sum(den * cnt for den, cnt in self.notes.items()) + self.apro

    def add_notes(self, breakdown: Dict[int, int]) -> None:
        for d, c in breakdown.items():
            self.notes[d] = self.notes.get(d, 0) + c

    def remove_notes(self, breakdown: Dict[int, int]) -> None:
        for d, c in breakdown.items():
            if self.notes.get(d, 0) < c:
                raise ValueError("Nincs elég címlet a kivételhez.")
        for d, c in breakdown.items():
            self.notes[d] -= c

    def add_apro(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("Apró összeg nem lehet negatív.")
        self.apro += amount

    def remove_apro(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("Apró összeg nem lehet negatív.")
        if self.apro < amount:
            raise ValueError("Nincs elég apró a kivételhez.")
        self.apro -= amount

    def save(self, path: Path = SAVE_PATH) -> None:
        data = {"notes": self.notes, "apro": self.apro}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path = SAVE_PATH) -> "Drawer":
        if path.exists():
            data = json.loads(path.read_text())
            notes = {int(k): int(v) for k, v in data.get("notes", {}).items()}
            for d in NOTE_DENOMS:
                notes.setdefault(d, 0)
            apro = int(data.get("apro", 0))
            return cls(notes=notes, apro=apro)
        return cls()


def bounded_change_notes(amount: int, available: Dict[int, int]) -> Optional[Dict[int, int]]:
    """
    Készletkorlátos visszajáró a *nagy* címletekből (>=200).
    Greedy + visszalépés kis fával.
    """
    denoms = sorted(NOTE_DENOMS, reverse=True)

    def search(idx: int, remaining: int, cur: Dict[int, int]) -> Optional[Dict[int, int]]:
        if remaining == 0:
            return dict(cur)
        if idx >= len(denoms):
            return None

        d = denoms[idx]
        max_use = min(remaining // d, available.get(d, 0))
        for k in range(max_use, -1, -1):
            if k:
                cur[d] = k
            else:
                cur.pop(d, None)
            res = search(idx + 1, remaining - d * k, cur)
            if res is not None:
                return res
        return None

    return search(0, amount, {})


def format_notes(br: Dict[int, int]) -> str:
    if not br:
        return "–"
    return ", ".join(f"{d} Ft x {c} db" for d, c in sorted(br.items(), reverse=True))


def input_initial_drawer(drawer: Drawer) -> None:
    print("\nKezdőkészlet megadása (Enter: kihagyás, marad 0):")
    for d in sorted(NOTE_DENOMS, reverse=True):
        while True:
            raw = input(f"  {d} Ft darabszám: ").strip()
            if raw == "":
                break
            try:
                n = int(raw)
                if n < 0:
                    raise ValueError
                drawer.notes[d] = n
                break
            except Exception:
                print("  Érvénytelen érték, próbáld újra.")
    while True:
        raw_apro = input("  Apró összeg (100/50/20/10/5 összesen, Ft): ").strip()
        if raw_apro == "":
            break
        try:
            a = int(raw_apro)
            if a < 0 or a % COIN_MIN_UNIT != 0:
                raise ValueError
            drawer.apro = a
            break
        except Exception:
            print(f"  Érvénytelen érték. Nem negatív és {COIN_MIN_UNIT}-tel osztható szám kell.")


def start_tx_snapshot(drawer: Drawer) -> None:
    """Elmenti globálisan a tranzakció előtti állapotot (deepcopy)."""
    global _tx_state
    _tx_state = deepcopy(drawer_to_state(drawer))


def cancel_tx_restore(drawer: Drawer) -> None:
    """Visszaállítja a tranzakció előtti állapotot és törli a snapshotot."""
    global _tx_state
    if _tx_state is None:
        return
    st = _tx_state
    # Állapot visszatöltése a meglévő objektumba
    notes = {int(d): int(c) for d, c in st.get("bankjegyek", {}).items()}
    for d in NOTE_DENOMS:
        notes.setdefault(d, 0)
    drawer.notes.clear()
    drawer.notes.update(notes)
    drawer.apro = int(st.get("apro", 0))
    _tx_state = None
    print("Tranzakció visszavonva. Kassza változatlan.")


def finalize_tx_and_clear_snapshot() -> None:
    """Véglegesíti a tranzakciót: törli a snapshotot."""
    global _tx_state
    _tx_state = None


def drawer_to_state(drawer: Drawer) -> Dict:
    """Átalakítja a fiók állapotát a storage modul által elvárt formára."""
    bankjegyek = {str(d): int(drawer.notes.get(d, 0)) for d in NOTE_DENOMS}
    apro = int(drawer.apro)
    osszesen = sum(d * c for d, c in drawer.notes.items()) + apro
    return {"bankjegyek": bankjegyek, "apro": apro, "osszesen": int(osszesen)}


def state_to_drawer(state: Dict) -> Drawer:
    notes = {int(d): int(c) for d, c in state.get("bankjegyek", {}).items()}
    # biztosítsuk az összes kulcsot
    for d in NOTE_DENOMS:
        notes.setdefault(d, 0)
    apro = int(state.get("apro", 0))
    return Drawer(notes=notes, apro=apro)


def main():
    global _tx_state
    print("=== Kassza & Visszajáró – egyszerűsített apró-kezeléssel ===")
    # Induláskor próbáljuk a mai állapotot betölteni
    today_state = storage_load_state()
    if today_state is not None:
        drawer = state_to_drawer(today_state)
    else:
        drawer = Drawer()
        print("Használd a :kezdet parancsot a mai induló készlet rögzítéséhez.")

    while True:
        print("\n--- Új tranzakció ---")
        raw_amount = input("Vásárlás összege (Ft) – Parancsok: :vissza (megszakítás), :visszavon (utolsó törlése), :ment, :betolt YYYY-MM-DD, :nullaz, :allapot, q (kilépés): ").strip()
        lower_raw = raw_amount.lower()
        if lower_raw in {"q", "quit", "exit"}:
            print("Kilépés. Állapot mentése...")
            storage_save_state(drawer_to_state(drawer))
            break
        # Parancsok kezelése
        if lower_raw.startswith(":"):
            cmd = lower_raw.split()
            name = cmd[0]
            if name == ":kezdet":
                input_initial_drawer(drawer)
                storage_save_state(drawer_to_state(drawer))
                print(f"Kassza mentve. Összesen: {drawer.total():,} Ft".replace(",", " "))
                continue
            elif name == ":ment":
                storage_save_state(drawer_to_state(drawer))
                print("Aktuális állapot elmentve a mai naphoz.")
                continue
            elif name in {":visszavon", ":undo"}:
                day = cmd[1] if len(cmd) > 1 else None
                last = read_last_tx(day)
                if not last:
                    print("Nincs visszavonható tranzakció.")
                    continue
                # Kiinduló állapot betöltése (adott nap vagy ma)
                if day is None:
                    target_drawer = drawer
                else:
                    st = storage_load_state(day)
                    if st is None:
                        print("Nincs mentett állapot erre a napra.")
                        continue
                    target_drawer = state_to_drawer(st)

                delta = last.get("delta", {})
                delta_notes = {int(k): int(v) for k, v in delta.get("notes", {}).items()}
                delta_apro = int(delta.get("apro", 0))

                # Invert alkalmazása: bankjegyek[d] -= delta[d]; apro -= delta_apro
                new_notes = dict(target_drawer.notes)
                for d in NOTE_DENOMS:
                    dv = delta_notes.get(d, 0)
                    new_cnt = new_notes.get(d, 0) - dv
                    if new_cnt < 0:
                        print("Inkonzisztens napló, nem vonható vissza.")
                        break
                    new_notes[d] = new_cnt
                else:
                    new_apro = target_drawer.apro - delta_apro
                    if new_apro < 0:
                        print("Inkonzisztens napló, nem vonható vissza.")
                        continue
                    # alkalmazzuk
                    target_drawer.notes = new_notes
                    target_drawer.apro = new_apro

                    # mentés ugyanarra a napra és napló csonkítása
                    if day is None:
                        storage_save_state(drawer_to_state(target_drawer))
                    else:
                        # mentés konkrét napra
                        state = drawer_to_state(target_drawer)
                        out_path = Path("data") / f"{day}_drawer.json"
                        out_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                    truncate_last_tx(day)
                    print(f"Utolsó tranzakció visszavonva. Új összesen: {target_drawer.total():,} Ft".replace(",", " "))
                continue
            elif name == ":betolt":
                if len(cmd) < 2:
                    print("Használat: :betolt YYYY-MM-DD")
                    continue
                day = cmd[1]
                st = storage_load_state(day)
                if st is None:
                    print("Nincs mentett állapot erre a napra.")
                else:
                    drawer = state_to_drawer(st)
                    print(f"Állapot betöltve: {day}. Összesen: {drawer.total():,} Ft".replace(",", " "))
                continue
            elif name == ":nullaz":
                st = storage_reset_state()
                drawer = state_to_drawer(st)
                print("Kassza nullázva és elmentve mára.")
                continue
            elif name == ":allapot":
                print("\nJelenlegi kassza állapot:")
                for d in sorted(NOTE_DENOMS, reverse=True):
                    print(f"  {d:>5} Ft : {drawer.notes.get(d,0)} db")
                print(f"  Apró összeg: {drawer.apro} Ft")
                print(f"Összesen a kasszában: {drawer.total():,} Ft".replace(",", " "))
                continue
            else:
                print("Ismeretlen parancs.")
                continue
        try:
            amount = int(lower_raw)
            if amount <= 0:
                raise ValueError
            if amount % COIN_MIN_UNIT != 0:
                print(f"  Figyelem: az összeg legyen {COIN_MIN_UNIT}-tel osztható.")
                continue
        except Exception:
            print("  Érvénytelen összeg.")
            continue

        # Tranzakció indul – snapshot készítése
        start_tx_snapshot(drawer)

        print("\nAdd meg a VEVŐ által adott pénzt. Példák:")
        print("  2000                   (egyetlen 2000 Ft)")
        print("  2000x1, 1000x1, 200x1  (nagy címletek)")
        print("  apro:150               (apró összege Ft-ban)")
        print("  2000x1, apro:100       (kevert)")
        raw_tendered = input("Vevő által adott (Ft) – Parancsok: :vissza (megszakítás), :visszavon (utolsó törlése), :ment, :betolt YYYY-MM-DD, :nullaz, :allapot, q (kilépés): ").strip()
        if raw_tendered == "":
            print("  Megszakítva.")
            # Tranzakció megszakadt – snapshot törlés
            finalize_tx_and_clear_snapshot()
            continue
        if raw_tendered.strip().lower() == ":vissza":
            cancel_tx_restore(drawer)
            continue

        try:
            tender_notes, tender_apro = parse_tender(raw_tendered)
        except ParseError as e:
            print(f"  Hiba: {e}")
            # Hibás megadás – új tranzakció indul, snapshot törlés
            finalize_tx_and_clear_snapshot()
            continue

        tender_total = sum(d * c for d, c in tender_notes.items()) + tender_apro
        if tender_total < amount:
            print(f"  A vevő által adott összeg ({tender_total} Ft) kevesebb, mint a fizetendő ({amount} Ft).")
            # Új tranzakció, snapshot törlés
            finalize_tx_and_clear_snapshot()
            continue

        # Előbb berakjuk a tenderedet a kasszába, utána visszaadunk:
        drawer.add_notes(tender_notes)
        drawer.add_apro(tender_apro)

        change = tender_total - amount
        print(f"\nFizetendő: {amount} Ft | Adott: {tender_total} Ft | Visszajáró: {change} Ft")

        if change == 0:
            print("Nincs visszajáró. Kassza frissítve.")
            # Naplózás (nincs visszajáró)
            ts = date.today().isoformat()
            from datetime import datetime as _dt
            ts = _dt.now().isoformat(timespec="seconds")
            entry = {
                "ts": ts,
                "amount_due": amount,
                "buyer_given": {
                    "notes": {str(d): int(c) for d, c in tender_notes.items()},
                    "apro": int(tender_apro),
                },
                "change": {
                    "notes": {},
                    "apro": 0,
                },
                "delta": {
                    "notes": {str(d): int(c) for d, c in tender_notes.items()},
                    "apro": int(tender_apro),
                },
                "total_after": drawer.total(),
            }
            append_txlog(entry)
            storage_save_state(drawer_to_state(drawer))
            # Sikeres tranzakció – snapshot törlés
            finalize_tx_and_clear_snapshot()
            continue

        # 1) próbáljuk nagy címletekből kiadni, amennyire lehet
        notes_only = bounded_change_notes(change, drawer.notes)
        notes_given: Dict[int, int] = {}
        apro_given = 0

        if notes_only is not None:
            # sikerült teljes egészében nagy címletekből
            notes_given = notes_only
        else:
            # 2) próbáljuk meg: nagy címletek részben + maradék apró
            # strat: greedy a nagy címletekre, majd a maradékot apróból, ha elég
            # egy egyszerű iter: csökkentsük a nagy címleteket amíg a maradékot ki tudjuk fizetni apróból
            remaining = change
            notes_used = {d: 0 for d in NOTE_DENOMS}
            for d in sorted(NOTE_DENOMS, reverse=True):
                use = min(remaining // d, drawer.notes.get(d, 0))
                if use > 0:
                    notes_used[d] = use
                    remaining -= d * use
            # maradék apróból?
            if remaining % COIN_MIN_UNIT == 0 and drawer.apro >= remaining:
                notes_given = {d: c for d, c in notes_used.items() if c > 0}
                apro_given = remaining
            else:
                # Ha így sem megy, próbáljunk visszalépni egy kicsit (csökkentsük a nagy címletek használatát)
                success = False
                # egyszerű visszalépő próbálgatás pár lépésig
                for d in sorted(NOTE_DENOMS, reverse=True):
                    while notes_used[d] > 0:
                        notes_used[d] -= 1
                        remaining += d
                        if remaining % COIN_MIN_UNIT == 0 and drawer.apro >= remaining:
                            notes_given = {dd: cc for dd, cc in notes_used.items() if cc > 0}
                            apro_given = remaining
                            success = True
                            break
                    if success:
                        break
                if not success:
                    # Nem sikerül — visszavonjuk a tranzakciót
                    drawer.remove_notes(tender_notes)
                    try:
                        drawer.remove_apro(tender_apro)
                    except Exception:
                        # elvileg nem fordulhat elő, de védjük
                        pass
                    print("  Nem tudok pontos összeget visszaadni a jelenlegi készletből. Tranzakció visszavonva.")
                    # Sikertelen tranzakció – snapshot törlés
                    finalize_tx_and_clear_snapshot()
                    continue

        # Kivét a kasszából a számított visszajáróra:
        if notes_given:
            drawer.remove_notes(notes_given)
        if apro_given:
            drawer.remove_apro(apro_given)

        print("\nVisszajáró:")
        print(f"  Bankjegyek: {format_notes(notes_given)}")
        print(f"  Apró: {apro_given} Ft")

        print("\nMaradék kassza:")
        for d in sorted(NOTE_DENOMS, reverse=True):
            print(f"  {d:>5} Ft : {drawer.notes.get(d,0)} db")
        print(f"  Apró összeg: {drawer.apro} Ft")
        print(f"Összesen a kasszában: {drawer.total():,} Ft".replace(",", " "))

        # Naplózás (visszajáróval)
        from datetime import datetime as _dt
        ts = _dt.now().isoformat(timespec="seconds")
        delta_notes = {}
        for d in set(list(tender_notes.keys()) + list(notes_given.keys())):
            delta = tender_notes.get(d, 0) - notes_given.get(d, 0)
            if delta != 0:
                delta_notes[str(d)] = int(delta)
        entry = {
            "ts": ts,
            "amount_due": amount,
            "buyer_given": {
                "notes": {str(d): int(c) for d, c in tender_notes.items()},
                "apro": int(tender_apro),
            },
            "change": {
                "notes": {str(d): int(c) for d, c in notes_given.items()},
                "apro": int(apro_given),
            },
            "delta": {
                "notes": delta_notes,
                "apro": int(tender_apro - apro_given),
            },
            "total_after": drawer.total(),
        }
        append_txlog(entry)
        storage_save_state(drawer_to_state(drawer))
        # Sikeres tranzakció – snapshot törlés
        finalize_tx_and_clear_snapshot()


if __name__ == "__main__":
    main()
