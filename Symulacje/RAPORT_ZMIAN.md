# Raport wdrożonych zmian (v2.1.0 TX + RX) – 2026-10-11

Wgrywać **oba** urządzenia (zmieniony wspólny `log_protocol.h`). Kompilacja: `pio run` TX i RX = SUCCESS (przypięte wersje). Symulacje: 44 PASS, 0 FAIL (`python run_all.py`).

| # | Zmiana | Gdzie | Wynik w symulacji |
|---|---|---|---|
| 4 | brak ponownego discovery, gdy odbiornik nieznany; po 1 nieudanym cyklu brak wybudzeń na ponowienia | TX `main.cpp`, `config.h` | awaria RX 5 dni: 1,2× energii (było 6,5×), 5,2 wybudzeń/dobę (było 27,6) |
| 5 | czujnik zasilany tuż przed pomiarem | TX `main.cpp` | – |
| 6 | czas 64-bitowy, wiek w NVS bez limitu 46 dni | RX `main.cpp`, `storage.cpp`, `display.*` | dioda po 50–100 dniach nadal czerwona |
| 7 | wywóz po 2 zgodnych cyklach lub po fizycznym resecie TX | TX `measurement.*`, `main.cpp` | fałszywe 150 cm przez 1 cykl nie ustawia „pusty”; wywóz widoczny po ~8 h, po resecie TX po ~0,7 h |
| 8 | bezpiecznik czasowy 10 min | TX `main.cpp` | – (nie do zasymulowania; patrz niżej) |
| 12 | restart po błędzie startu RX | RX `main.cpp` | – |
| 13 | kolejka FreeRTOS dla pakietów ESP-NOW | RX `espnow_receiver.*` | – |
| 14 | przypięte wersje platformy i bibliotek | oba `platformio.ini` | – |
| 15 | prognoza regresją liniową, zakres dni | RX `display.*`, `config.h` | błąd mediany 4 % / p90 10 % (EWMA 18 % / 42 %) |
| 18 | wznawianie przerwanego rekordu logu (`nextSeq`) | `log_protocol.h`, TX `log_sync.cpp`, RX `txlog.*` | 30 % strat/kierunek: 20 rekordów w ~55 wybudzeniach (wcześniej praktycznie nigdy) |
| 20 | reset historii przy pojedynczym skoku >50 cm; RESET → pierwszy pakiet = nowy start | RX `display.cpp` | po wywozie prognoza wraca po 8 pomiarach |
| 21 | dokumentacja | `AGENTS.md`, `CLAUDE.md`, `WERSJA_ZMIANY.txt` | – |

Pominięte zgodnie z decyzją: 1, 2, 3, 9, 10, 11, 16, 17, 19, przypadkowy RESET. `FW_VERSION` = 2.1.0.

## Do sprawdzenia na urządzeniu (nie da się potwierdzić symulacją)
1. **TX po wgraniu:** w logu pierwszego cyklu: czyste RTC (`rtcMagic`), czujnik włącza się dopiero przy pomiarze (słychać tykanie/„klik” po starcie, nie od razu), cykl ~3 min.
2. **Bezpiecznik 10 min:** test: tymczasowo ustaw `WATCHDOG_TIMEOUT_MS 60000`, wgraj, zobacz, że TX po minucie idzie spać, a następny rekord logu zawiera „przerwał bezpiecznik czasowy”; wróć do 600000.
3. **Wywóz:** (a) bez resetu TX – RX po RESET pokazuje „Oczekiwanie” do 2. zgodnego cyklu (do ~12 h); (b) po odłączeniu/włączeniu zasilania TX – wartość pojawia się po jednym cyklu (~3–4 min).
4. **RX:** przyciski RESET, ekran z zakresem prognozy (`3-4 dni`, `>99 dni`), brak błędów w `TXLOG`; log TX nadal się pobiera `python tools/txlog_pobierz.py` (po wgraniu obu).
5. **Awaria RX (wyłącz na dobę):** TX ma robić ponowienia tylko po pierwszym nieudanym cyklu; w logu „nieudanych cykli z rzędu”.
