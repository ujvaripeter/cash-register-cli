Kassza CLI – parancsok

- `:kezdet` — induló készlet felvitele és mentése (mai nap).
- `:ment` — aktuális állapot mentése mára.
- `:betolt <YYYY-MM-DD>` — korábbi napi állapot betöltése.
- `:nullaz` — üres kassza létrehozása és mentése mára.
- `:allapot` — jelenlegi állapot kiírása.
- `:vissza` — folyamatban lévő tranzakció megszakítása és teljes visszaállítás.

Tranzakciónapló és utólagos visszavonás
--------------------------------------
- A sikeresen lezárt tranzakciók JSONL formátumban naplózódnak: `data/YYYY-MM-DD_txlog.jsonl` (soronként egy JSON).
- Bejegyzés tartalma: időbélyeg (`ts`), fizetendő (`amount_due`), vevő által adott (`buyer_given`), visszajáró (`change`), nettó változás (`delta`), lezárás utáni összesen (`total_after`).
- Utolsó tranzakció visszavonása: `:visszavon` (alias: `:undo`).
  - Opcionális nap megadás: `:visszavon YYYY-MM-DD`.
  - Ha nincs visszavonható tranzakció: „Nincs visszavonható tranzakció.”
  - Siker esetén: a napló utolsó sora törlődik és az állapot mentésre kerül ugyanarra a napra.

Induláskor, ha nincs mai állapot, a program jelzi: „Használd a :kezdet parancsot a mai induló készlet rögzítéséhez.”
