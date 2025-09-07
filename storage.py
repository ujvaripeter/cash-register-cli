#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Egyszerű napi állapot tároló JSON-ban.

Formátum:
{
  "bankjegyek": { "20000": int, "10000": int, "5000": int, "2000": int, "1000": int, "500": int, "200": int },
  "apro": int,
  "osszesen": int
}

Mentés: data/YYYY-MM-DD_drawer.json
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, Optional

# Címletek sorrendje a feladat szerint
NOTE_DENOMS = [20000, 10000, 5000, 2000, 1000, 500, 200]

DATA_DIR = Path("data")


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _file_for(day: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"{day}_drawer.json"


def _normalize_state(state: Dict) -> Dict:
    """Töltse fel a hiányzó kulcsokat 0-val, és számolja újra az összesent."""
    bankjegyek = {str(d): int(0) for d in NOTE_DENOMS}
    for k, v in state.get("bankjegyek", {}).items():
        bankjegyek[str(k)] = int(v)
    apro = int(state.get("apro", 0))
    osszesen = sum(int(k) * int(v) for k, v in bankjegyek.items()) + apro
    return {"bankjegyek": bankjegyek, "apro": apro, "osszesen": osszesen}


def save_state(state: Dict) -> Path:
    """Mentse a mai állapotot a data/ mappába. Visszaadja a fájl elérési útját."""
    day = _today_str()
    path = _file_for(day)
    norm = _normalize_state(state)
    path.write_text(json.dumps(norm, ensure_ascii=False, indent=2))
    return path


def load_state(day: Optional[str] = None) -> Optional[Dict]:
    """Betölti a megadott nap (YYYY-MM-DD) állapotát. Ha nincs, None."""
    if day is None:
        day = _today_str()
    path = _file_for(day)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return _normalize_state(data)
    except Exception:
        # Ha sérült, viselkedjünk úgy, mintha nem lenne
        return None


def reset_state() -> Dict:
    """Üres állapot (minden 0) létrehozása és azonnali mentése mára."""
    empty = {
        "bankjegyek": {str(d): 0 for d in NOTE_DENOMS},
        "apro": 0,
        "osszesen": 0,
    }
    save_state(empty)
    return empty

