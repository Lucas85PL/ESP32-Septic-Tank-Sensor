# Symulacje TX / RX (Szambo 2.0.0)

Symulowane kontrolery TX i RX + świat (zbiornik, czujnik JSN-SR04T, radio) do testowania firmware **bez zmieniania kodu źródłowego**.

```
python run_all.py          # ~8 s, zapisuje wyniki.md (tabela PASS/FAIL/INFO) – wymaga tylko Pythona 3
```

| Katalog | Zawartość |
|---|---|
| `fw/tx_measurement.py` | port 1:1 `TX/src/measurement.cpp` + stałe `config.h` (klastry, okno napełniania, strefa martwa) |
| `fw/tx_main.py` | port `main.cpp::setup()` (cykl, ponowienia, plan snu, RTC/flash), `espnow_manager` (czasy), `ref_store`, commit logu |
| `fw/protocol.py` | port `event_logger` (meta/rekordy), `log_sync.cpp` oraz `txlog.cpp::handleChunk` (RX) + kanał z stratami |
| `fw/rx_logic.py` | port RX: `main.cpp` (alarm 25 h, dioda, NVS) + `display.cpp` (EWMA, procent) – z arytmetyką `uint32 millis()` |
| `env/world.py` | zbiornik (napełnianie, wywozy), czujnik (szum, timeouty, ślepota, echo, strefa martwa, temperatura), radio |
| `env/e2e.py` | pętla end-to-end: TX ↔ radio ↔ RX, awarie RX, reset zasilania TX/RX w dowolnej chwili |
| `tests/t_a…t_f` | A pomiary · B maszyna stanów/energia/zasilanie · C protokół logów · D odbiornik · E Monte Carlo · F weryfikacja poprawek |
| `fw/rx_v2.py`, `tests/t_g_history.py` | **propozycja v2** (jeszcze nie w firmware): historia 14 punktow w TX (flash) + pakiet z historia, RX bez wlasnej historii, odciecie po RESET (epoka+seq), prior 6 cm/dobe do 36 h (pomaranczowy) potem regresja (zielony); `Run(v2=True)`, STARY vs NOWY |
| `RAPORT_ANALIZY.md` | **abstrakt problemów + rekomendowane poprawki** |

## Ograniczenia (ważne)
* Na tym komputerze nie ma kompilatora C++ ani `pio`, więc to **porty Pythonowe** firmware (nie kompilacja prawdziwego kodu). Każda zmiana w `measurement.cpp`, `main.cpp`, `txlog.cpp`, `display.cpp` wymaga aktualizacji portu. Następny krok, jeśli chcesz: środowisko `[env:native]` w PlatformIO z atrapami Arduino/ESP-NOW i kompilacja *prawdziwych* plików.
* Elementy sprzętowe (stan GPIO23 w deep sleep, pobór prądu, zachowanie JSN-SR04T w strefie martwej, MAC-retransmisje ESP-NOW) są **modelowane/założone**, nie zmierzone – w raporcie oznaczone jako „do weryfikacji na sprzęcie”.
* Model energii (`tests/t_b_system.py`: 45 mA CPU, 30 mA czujnik, 110 mA Wi-Fi) służy do porównań względnych, nie do prognozy czasu pracy baterii.
* Poprzednie symulacje logiki pomiarów: `TX 2.0.0/symulacja/` (rój agentów, wersje V3–V5). Port z tego folderu jest niezależny, ale wyniki E1/E2 są z nimi zgodne.
