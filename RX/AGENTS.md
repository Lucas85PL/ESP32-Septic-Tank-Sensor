# ESP32 RX 2.0.0 — Dokumentacja projektu (płytka E32R28T)

> **Wersja 2.2.0** = RX v0.9.0 + odbiór logów nadajnika (komendy `TXLOG*`, `tools/txlog_pobierz.py`, opis w `KOMENDY_LOGI_TX.txt`) + historia pomiarów z pakietu TX (prognoza od razu po restarcie). Para z `../TX 2.0.0` (TX 2.2.0 — **wgrywać OBA**).

## Opis
Odbiornik pomiarów odległości dla ESP32E 2.8" z dotykowym wyświetlaczem (SKU **E32R28T**: ILI9341 320×240, dotyk rezystancyjny XPT2046). Nasłuchuje danych z nadajnika przez ESP-NOW, wyświetla poziom wypełnienia zbiornika i prognozuje datę pełnego zapełnienia. Pamięta ostatni poprawny pomiar po utracie zasilania.

Wersja pod poprzednią płytkę (ST7735S 160×128, v0.8.9) jest w `backup_ST7735_v0.8.9/`.
Makiety trzech koncepcji wyglądu (wybrana: **A – Pierścień**) są w `wizualizacje/`.

## Struktura plików

| Plik | Opis |
|------|------|
| `src/config.h` | Wszystkie stałe konfiguracyjne (piny, progi, czasy) |
| `src/display.h/cpp` | Ekrany (motyw „Pierścień”), dioda statusu, przycisk RESET, odczyt dotyku, historia pomiarów, prognoza (regresja liniowa) |
| `src/storage.h/cpp` | Trwały zapis ostatniego poprawnego pomiaru (NVS / flash) |
| `src/espnow_receiver.h/cpp` | ESP-NOW: odbiór pakietów, ACK, odpowiedź na discovery |
| `src/meas_protocol.h` | Pakiet pomiaru z historią `MeasurementPacketV2` (magic 0xA9) — **identyczny plik w projekcie TX** |
| `src/history_sync.h/cpp` | Historia z pakietu TX: odrzucanie starych pakietów (epoka + seq), odcięcie po RESET, przycinanie po wywozie, blob do NVS |
| `src/main.cpp` | Główna pętla |
| `platformio.ini` | Biblioteki: Adafruit GFX, Adafruit ILI9341 |

## Hardware

### Wyświetlacz ILI9341 (HSPI)
| Sygnał | GPIO |
|--------|------|
| MOSI | 13 |
| MISO | 12 |
| SCLK | 14 |
| CS | 15 |
| DC | 2 |
| RST | EN (−1) |
| Podświetlenie | **21** |

### Dotyk XPT2046 (osobna magistrala, VSPI)
| Sygnał | GPIO |
|--------|------|
| CLK | 25 |
| MOSI | 32 |
| MISO | 39 |
| CS | 33 |
| IRQ | 36 (nieużywane – odczyt przez polling) |

Orientacja: pozioma. `DISPLAY_ROTATION 3` = USB z **lewej** patrząc na ekran (obudowa v2.0, bieżąca); `1` = USB z prawej (obudowa v1.0). Dotyk odwraca się automatycznie.

## Wymiary mechaniczne (do obudowy)
Źródło: rysunek producenta [E32R28T-1 Size V1.0](https://www.lcdwiki.com/res/E32R28T-1/E32R28T-1_Size.pdf) (render w `wizualizacje/E32R28T_wymiary.png`). Pionowo (portret): USB u dołu.

| Element | Wymiar |
|---------|--------|
| PCB | **50,00 × 86,00 mm**, narożniki R3,5 |
| Otwory montażowe | **4 × Ø3,2 mm** (pole pod łeb/podkładkę Ø4,8), rozstaw **42,00 × 78,00 mm**, czyli 4,0 mm od każdej krawędzi |
| Obszar wyświetlania (LCD AA) | 43,20 × 57,60 mm |
| Obszar widoczny dotyku (RTP VA) | 45,20 × 59,45 mm – minimalne okno w obudowie |
| Obszar aktywny dotyku (RTP AA) | 44,20 × 58,60 mm |
| Szyba dotykowa (RTP OD) | 49,60 × 68,80 mm |
| Panel LCD (BL) | 50,00 × 69,20 mm |
| Grubość od przodu | 5,60 mm (PCB 1,6 + taśma 0,5 + LCD 2,3 + dotyk 1,2) |
| Wysokość elementów z tyłu | do 5,09 mm (SMD / moduł ESP32 / złącza) |

Orientacyjnie całkowita grubość płytki to ok. 10,7 mm. Wnęka obudowy z tyłu musi zmieścić złącza (USB-C, BAT, SPEAKER, UART). Przyciski BOOT i RESET sprzętowy są przy USB.

Uwaga: rysunek jest dla rewizji E32R28T-1 (2025, w nocie kontroler ST7789P3). Twoja płytka zgłasza ILI9341 (ID 0x9341), więc to starsza lub inna rewizja i **warto zmierzyć suwmiarką** rozstaw otworów i grubość przed drukiem/frezowaniem obudowy.

## Obudowa (Fusion, druk 3D)
Skrypty Fusion w `obudowa_fusion/`: `RX_obudowa` (v1.0, otwarty tył, USB z prawej), `RX_obudowa_v2` (plecki na przelot przez PCB – nieużywana) i `RX_obudowa_v3` (44,6 mm, plecki cofnięte o 2,2 mm) i **`RX_obudowa_v3_1` (bieżąca)**: prostopadłościan 90,8 × 58 × **49,6 mm** bez stopki, plecki równo z tyłem (flush), USB z lewej; płytka na przednich słupkach jak w v1 (**4 × M3 × 6**), plecki na **osobnych słupkach w tylnych rogach** (**4 × M3 × 8**), nic nie dociska płytki. Płytkę wkłada się od tyłu **po skosie** (ok. 35–40° wokół dłuższej osi, wsunąć na ok. 20 mm, potem wyprostować i dosunąć do słupków) – geometria dobrana symulacją (`symulacja_wkladania.py`). Uruchomienie: Fusion → Shift+S → Scripts → + → wskaż folder skryptu. Eksport: prawy klik na ciele → Save As Mesh → 3MF (Bambu Studio).

## Funkcje

### 1. Odbiór i ACK (bez zmian względem v0.8.9)
Nadajnik robi broadcast (discovery, `packetId=0`) → odbiornik odpowiada ACK → nadajnik zapamiętuje MAC. Odbiornik nie ma wpisanego MAC na stałe, więc **inny MAC płytki nie wymaga żadnej konfiguracji**. Na czas wymiany płytki wyłącz starą, żeby nadajnik nie wybrał jej zamiast nowej.

### 2. Pamięć ostatniego pomiaru
- Zapis w NVS przy każdym poprawnym pomiarze i co godzinę (wiek pomiaru).
- Po włączeniu zasilania płytka pokazuje ostatni poprawny pomiar zamiast „Oczekiwanie na dane”.
- **Ograniczenie:** brak zegara RTC – czas bez zasilania nie jest liczony do wieku pomiaru. Po długiej awarii dioda może być zielona mimo starego pomiaru.
- Od 2.2.0 historia (ostatni pakiet TX: do 14 pomiarów z wiekiem) jest zapisywana w NVS przy każdym pakiecie i odtwarzana po restarcie – prognoza „Pełny za” jest od razu widoczna. Bez zapisu (pierwszy start po aktualizacji): „-- dni” do pierwszego pakietu.

### 3. Dioda statusu (prawy górny róg)
Wiek ostatniego **poprawnego** pomiaru:

| Wiek | Dioda |
|------|-------|
| < 25 h | zielona |
| 25 – 50 h | pomarańczowa |
| > 50 h | czerwona, miga (co 0,5 s) |

Progi: `STATUS_ORANGE_AFTER_MS`, `STATUS_RED_AFTER_MS`, `STATUS_BLINK_MS` w `config.h`.

### 4. Przycisk RESET (prawy dolny róg, dotyk)
Przytrzymanie **3 s** (pasek postępu na przycisku) → kasuje zapis w pamięci, zeruje historię i wraca do „Oczekiwanie na dane” (jak przy pierwszym uruchomieniu). Od 2.2.0 zapisuje też **odcięcie** (epoka + seq ostatniego pakietu): pakiety TX ze starą historią (sprzed wywozu) są ignorowane, dopóki TX ich nie wyczyści. Kolejność resetów RX/TX po wywozie nie ma znaczenia. Zaprojektowany pod rysik: `TOUCH_Z_MIN 300` (palec wymaga ok. 100). Krótki dotyk nic nie robi. Dotyk poza przyciskiem jest ignorowany.

## Ekrany (motyw „Pierścień”)
1. **Oczekiwanie na dane** – pusty pierścień, napis, numer kanału.
2. **Pomiar** – pierścień z procentem (zielony < 60%, żółty 60–80%, czerwony ≥ 80%), po prawej: wolne miejsce [cm], czas od pomiaru, „Pełny za” [dni].
3. **Brak pomiaru** (po 25 h bez pakietu) – wykrzyknik, „BRAK POMIARU”, ostatni pomiar (godz. temu / cm / %), przycisk RESET.
4. **Błąd czujnika** (6 niepoprawnych pomiarów z rzędu) – pusty pierścień, „--”, czerwony napis „BLAD CZUJNIKA”.
5. **Błąd startu** – „BLAD” + komunikat (np. „ESP-NOW init failed”).

Napisy są bez polskich znaków (wbudowane czcionki GFX ich nie mają).

## Obliczanie wypełnienia
```
corrected = raw - SENSOR_HEIGHT_OFFSET   (domyślnie 0 cm = bez korekty; ustaw w config.h)
percent   = (MAX_DISTANCE - corrected) / (MAX_DISTANCE - MIN_DISTANCE) * 100
```
Domyślne wartości przykładowe (`SENSOR_HEIGHT_OFFSET` 0, `MIN_DISTANCE` 25, `MAX_DISTANCE` 155):

| Raw | Corrected | Wypełnienie |
|-----|-----------|-------------|
| 25 cm | 25 cm | 100% |
| 90 cm | 90 cm | 50% |
| 155 cm | 155 cm | 0% |

Pomiary raw spoza zakresu 0…(`MAX_DISTANCE + SENSOR_HEIGHT_OFFSET + 25`) cm (domyślnie 180) są odrzucane. `MIN_DISTANCE` 25 = granica strefy martwej czujnika JSN-SR04T (100%). **Dopasuj `MAX_DISTANCE` (pusty zbiornik) i ewentualnie `SENSOR_HEIGHT_OFFSET` do własnego montażu.**

## Prognoza „Pełny za”
Historia (do 14 zatwierdzonych pomiarów z wiekiem) przychodzi w pakiecie z TX. Dwie fazy:
- **orientacyjna (pomarańczowa, `~N dni`)** – do czasu uzbierania 7 rzeczywistych pomiarów rozpiętych na 35 h (po wywozie od razu): zakładane tempo 6 cm/dobę (`FORECAST_PRIOR_CM_PER_DAY`),
- **z regresji liniowej (zielona)** – z ostatnich 14 pomiarów, wynik jako zakres dni (`3-4 dni`). Sztuczne 25.0 cm (strefa martwa) nie wchodzi do regresji.

Skok odległości w górę > 50 cm w odebranej historii (wywóz) odcina starsze punkty; po przycisku RESET pakiety ze starą historią są ignorowane (odcięcie epoka + seq).

## Kompilacja i wgrywanie
```
pio run -t upload
pio device monitor      # 115200 baud
```
Debug w monitorze można wyłączyć: `DEBUG_ENABLED false` w `config.h`.

## Lista kontrolna testów LIVE
- [ ] Po włączeniu: „Oczekiwanie na dane” (przy pierwszym uruchomieniu), kanał 1.
- [ ] Nadajnik znajduje odbiornik (w logu nadajnika: MAC odbiornika), pierwszy pakiet pojawia się na ekranie.
- [ ] Wartości zgodne z nadajnikiem (po korekcie `SENSOR_HEIGHT_OFFSET`), procent i kolor pierścienia.
- [ ] Dioda zielona; po 25 h pomarańczowa i ekran „BRAK POMIARU”; po 50 h czerwona migająca.
- [ ] Odłączenie zasilania na chwilę → po włączeniu wraca ostatni pomiar.
- [ ] RESET rysikiem 3 s → „Oczekiwanie na dane”; po ponownym wyłączeniu zasilania nadal „Oczekiwanie na dane”.
- [ ] Prognoza „Pełny za” pojawia się od razu po pierwszym pakiecie: pomarańczowa `~N dni` (orientacyjnie), po ok. 36 h zielona (regresja). Po restarcie RX (odłączenie zasilania) prognoza wraca od razu.
- [ ] Po wywozie: RESET RX + reset TX w dowolnej kolejności → brak starych danych w prognozie.

## Znane wzorce – NIE SĄ BŁĘDAMI
- `saveToRtc()` / `loadFromRtc()` w `display.cpp` są celowo niewywoływane (martwy kod).
- `esp_now_send()` wołane z `loop()`, nie z callbacku (unika deadlocku).
- Ekran/ostrzeżenie 25 h liczone od ostatniego **pakietu**, dioda – od ostatniego **poprawnego** pomiaru.
- Własny odczyt dotyku (`readTouch()`) zamiast biblioteki XPT2046 – zaszyty próg biblioteki był za wysoki dla palca.

## Historia zmian
### 2026-10-18 – 2.2.0 (para z TX 2.2.0 – wgrywać OBA)
Historia pomiarów przychodzi w pakiecie TX (`meas_protocol.h`, `MeasurementPacketV2`, magic 0xA9); RX zapisuje ją w NVS (blob `hist`) i odtwarza po restarcie, więc prognoza jest od razu widoczna po utracie zasilania i po wymianie płytki. Odcięcie po RESET (epoka + seq, NVS). Prognoza: regresja od 7 pomiarów / 35 h; wcześniej orientacyjna 6 cm/dobę (pomarańczowa `~N dni`), po uzbieraniu danych zielona. Stałe: `FORECAST_MIN_POINTS` 8→7, `FORECAST_MIN_SPAN_H` 35, `FORECAST_PRIOR_CM_PER_DAY` 6. Nowe pliki: `meas_protocol.h`, `history_sync.h/cpp`; zmiany: `storage`, `espnow_receiver`, `display`, `main`. Zweryfikowane w symulacji (`../Symulacje/`, testy G); **kod C++ nie był kompilowany na tej maszynie – zrób `pio run` przed wgraniem**.

### 2026-10-11 – 2.1.0
Czas 64-bit (dioda/alarm bez zawijania), kolejka FreeRTOS dla pakietów ESP-NOW, restart po błędzie startu, prognoza regresją, reset historii po wywozie, wznawianie logów TX (nextSeq), przypięte wersje w platformio.ini. Szczegóły: `WERSJA_ZMIANY.txt`.

### 2026-10-11 – 2.0.0
Odbiór logów nadajnika przez ESP-NOW (porcje z ACK) → LittleFS `/txlog.txt`; komendy Serial `TXLOG`, `TXLOG DUMP`, `TXLOG CLEAR`; skrypt `tools/txlog_pobierz.py` zapisujący log do pliku .txt. Poprawki grafiki: wyłączone zawijanie tekstu (litera „u" z „godz. temu" uciekała do drugiego wiersza), wypełnienie przycisku RESET wycinane do kształtu pigułki z czyszczeniem całego prostokąta (brak resztek po puszczeniu). Reszta bez zmian względem v0.9.0.

### 2026-10-09 – v0.9.0
Port na E32R28T (ILI9341 + XPT2046), pamięć ostatniego pomiaru (NVS), dioda statusu, przycisk RESET z przytrzymaniem 3 s, nowy motyw wizualny „Pierścień”. Szczegóły techniczne: `CLAUDE.md`.

### Wcześniejsze (płytka ST7735S)
v0.8.9 – predykcja EWMA zamiast regresji WLS (od 2.1.0 znów regresja, zwykła liniowa); v0.8.8 – `MAX_DISTANCE 145`; v0.8.6 – korekta offsetu czujnika 15 cm; v0.8.5 – ekran braku pomiaru po 25 h; v0.8.3 – ACK poza callbackiem; wcześniejsze – patrz `backup_ST7735_v0.8.9/`.
