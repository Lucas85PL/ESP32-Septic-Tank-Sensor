> **Uwaga (2026-10-11):** ten raport opisuje stan PRZED zmianami. Wdrożone zmiany i ich weryfikacja: `RAPORT_ZMIAN.md`.

# Analiza TX 2.0.0 + RX 2.0.0 – abstrakt problemów i rekomendowane poprawki

Data: 2026-10-11 · Zakres: pełny przegląd kodu (TX: 11 plików, RX: 9 plików) + symulacje w `Symulacje/` (86 wyników: 32 PASS, 7 FAIL = potwierdzone wady, 47 INFO). **W kodzie źródłowym niczego nie zmieniono.**
Odtworzenie: `python run_all.py` w folderze `Symulacje` (≈8 s). Szczegóły i surowe liczby: `wyniki.md`.

## 0. Werdykt
Rdzeń jest dobry: logika pomiarów (klastry + okno czasowe) daje **widok poprawny przez 97,9 % czasu bez usterek i 94,8 % z usterkami z Twojego logu** (ślepota, echo 25,4, losowe echa); TX nie wisi (najdłuższe wybudzenie 199 s w najgorszych scenariuszach), reset zasilania w dowolnym momencie jest bezpieczny, protokół logów dostarcza „dokładnie raz” przy stratach do 20 %/kierunek, śmieciowe pakiety nie psują RX.
Do „bulletproof” brakuje **4 realnych wad zachowania (W1–W4)** potwierdzonych symulacją, kilku twardych zabezpieczeń (W5–W10) i kilku usprawnień. Poniżej, wg ważności.

> Metoda i ograniczenia: porty Pythona 1:1 kodu C++ (brak kompilatora C++ na tym PC); sprzęt (GPIO23 w deep sleep, pobór prądu, JSN-SR04T w strefie martwej, retransmisje MAC) jest modelowany – oznaczone „[sprzęt]”.

---

## 1. Problemy potwierdzone symulacją (WYSOKI priorytet)

### W1 · Fałszywy alarm „BRAK POMIARU” dokładnie wtedy, gdy zbiornik jest pełny
* **Co:** TX potwierdza strefę martwą (<25 cm) dopiero po `DEADZONE_CONFIRM_CYCLES = 6` cyklach (36 h) i do tego milczy; RX ogłasza alarm po `NO_DATA_TIMEOUT` = 25 h. Okno 25–36 h to czerwony ekran + pomarańczowa dioda w krytycznym momencie („szambo pełne”).
* **Dowód:** D3 – zbiornik wchodzi w <25 cm w 107 h, TX raportuje 25,0 dopiero w 139 h, RX pokazuje alarm łącznie **11,2 h** (A7: raport po 36 h).
* **Poprawka (wybierz jedną):** (a) TX `DEADZONE_CONFIRM_CYCLES 3` (18 h) – zweryfikowane: alarm 0,0 h (F3); (b) RX `NO_DATA_TIMEOUT` 43 h – też 0,0 h (F3), bez ruszania logiki TX; (c) najlepiej: po 2 cyklach TX wysyła 25,0 z `validReadings = 0` jako „podejrzenie pełnego”, RX pokazuje „PRAWIE PEŁNY (niepotwierdzone)”.
* **Powiązane (A7/A7b, [sprzęt]):** strefa martwa jest wykrywana tylko dla odczytów <25 cm **rozproszonych** (σ ≥ 1,5 cm) i stanowiących ≥50 % próbek. Czujnik w strefie martwej dający stabilne ~22 cm, same timeouty lub 60 % timeoutów → **TX milczy bez końca**, RX po 25 h alarmuje do skutku. Trzeba zmierzyć, jak Twój JSN-SR04T zachowuje się <25 cm; jeśli bywa „cichy”, dodać regułę: ≥N kolejnych cykli z ≥80 % timeoutów/„<25”, a ostatni wynik ≤70 cm → traktuj jak strefę martwą.

### W2 · RX: wykrywanie opróżnienia nigdy nie działa → „Pełny za” bezsensowne przez ~2,5 doby po wywozie
* **Co:** `display.cpp::addToHistory` zlicza `_emptyCount` tylko dla **kolejnych skoków >50 cm** i wymaga 4. Po wywozie pierwszy pomiar skacze o +95 cm (licznik=1), następny jest znów ~160 (licznik zeruje się). `resetHistory()` po wywozie **nigdy się nie wykona**.
* **Skutek:** EWMA dostaje ujemną „szybkość” (−16 cm/h) → „-- dni” przez 9 kolejnych pomiarów (2,25 doby), potem wartości 29–32 dni zamiast 22 (D1: 0 resetów, 9 pustych odczytów).
* **Poprawka (1 linia):** reset przy pojedynczym skoku, bo wywóz jest walidowany już w TX (≥140 cm):
  ```cpp
  if (_lastDistanceForEmptyCheck > 0 && distanceCm > _lastDistanceForEmptyCheck + EMPTY_THRESHOLD) {
      resetHistory();            // wywóz: pojedyncze potwierdzone przez TX duże zwiększenie odległości
  }
  ```
  Zweryfikowane (F2): prognoza po wywozie 22, 29, 21, 21, 22… bez „-- dni”.

### W3 · Awaria odbiornika zużywa baterię TX ≈ 6,5× szybciej
* **Co:** gdy RX nie odpowiada, TX przy każdym regularnym cyklu robi: discovery 10 s → `sendValue` (3 próby) → **2× ponowne discovery po 10 s mimo że przed chwilą się nie udało** → potem 6 wybudzeń „retry” (30/30/30/60/60/120 min), każde z kolejną serią discovery (~35 s radia).
* **Dowód:** B2 – 27,6 wybudzeń/dobę (norma 4), radio 943 s/dobę (norma 3 s), ≈ **6,5× energii** w modelu (45/30/110 mA). Sekwencja doby: `CRRRRRR CRRRRRR…` (B2b).
* **Poprawka (zweryfikowana F1):** (a) w `sendValue()` nie powtarzaj rediscovery, jeśli discovery w `initializeEspNow()` właśnie zawiodło → 4,5×; (b) dodatkowo licznik `failedRegular` w RTC: ponowienia tylko po **pierwszym** nieudanym cyklu regularnym → **1,2× normy**, powrót danych po włączeniu RX ≤ 2,7 h. Uwaga na ścieżkę retry: czujnik jest włączony od `setup()` podczas discovery (do 15 s) – włączaj MOSFET dopiero przed pomiarem.

### W4 · RX: po ~50 dniach bez danych dioda wraca do ZIELONEJ
* **Co:** `currentMillis - lastValidMillis` w `uint32_t` ms zawija się po 49,7 dnia. Zepsuty TX/rozładowana bateria >50 dni → dioda „wiek” znów zielona, mimo że ekran pokazuje alarm.
* **Dowód:** D5 – 49 d: czerwona, **50 d: zielona**, 51 d: pomarańczowa, 100 d: zielona.
* **Poprawka:** czas jako `uint64_t` z `esp_timer_get_time()/1000` (lub nasycanie wieku: po przekroczeniu `STATUS_RED_AFTER_MS` blokuj w czerwonym). Tak samo `storage.cpp` (`MAX_AGE_SECONDS`).

---

## 2. Ryzyka logiki pomiarów (ŚREDNI)

### W5 · Jednorazowe stabilne echo ≥140 cm jest akceptowane od razu jako „wywóz”
* A6: stabilne 150 cm przy prawdzie 60 → status OK, RX pokazuje „pusty”; po powrocie czujnika do normy poprawny wynik wraca dopiero po **5 cyklach = 30 h** (A6b). Zrzut z sondy/wyjęty czujnik w pustym pomieszczeniu to realny scenariusz.
* **Poprawka:** wzrost >5 cm do ≥140 cm akceptuj po **dwóch kolejnych cyklach** (RefState: `pendingRise`, wartość kandydata; ±5 cm). Koszt: wywóz widoczny 6 h później (nieistotne przy skali dób); zysk: brak 30 h fałszywego „pusty”.

### W6 · Prognoza „Pełny za” – EWMA(α=0,3) z odstępów 6 h jest szumowa
* D2: przy σ wyniku 1 cm błąd mediany 18 %, p90 42 %. Regresja liniowa z ostatnich 12 pomiarów (72 h): 7 % / 17 % (F5). Historia 14 punktów już istnieje w `_history[]` (dziś martwa).
* **Poprawka:** MNK po ostatnich 12–16 punktach z czasami odbioru; pokaż „–” przy małym nachyleniu; podawaj zakres („3–4 dni”).

### W7 · Szum powierzchni (sloshing)
* A2: σ ≤ 3 cm → 0 % straconych cykli; σ=5 cm → 8 %, σ=8 cm → 23 %, σ=12 cm → 42 %. Przy dopływie/napowietrzaniu rozważ szerszy klaster (`POOL_HALF_WIDTH_CM` adaptacyjny wg rozrzutu) – tylko jeśli takie warunki występują.

### W8 · Kompensacja temperatury [sprzęt]
* `SOUND_SPEED_CM_PER_US` stałe (20 °C). E3: −10 °C → −4,2 cm, 0 °C → −2,7 cm, +30 °C → +1,9 cm przy ~100 cm. Wpływ na logikę znikomy (okna w cm/dobę), ale wskazanie dryfuje sezonowo. DS18B20 przy czujniku albo korekta sezonowa; minimum – zapisz w dokumentacji.

---

## 3. Twarde zabezpieczenia / odporność (ŚREDNI–NISKI)

| ID | Problem | Rekomendacja |
|---|---|---|
| **W9** | **Brak zewnętrznego watchdoga na cyklu TX.** Pętle są ograniczone (max 199 s w symulacji), ale realne zawieszenie (LittleFS/Wi-Fi init) nie ma limitu → bateria. Brownout przy słabej baterii → pętla restartów z 160 s pomiarem. | `esp_timer` jednorazowy 480 s: wyłącz MOSFET + `esp_deep_sleep_start()`; lub TWDT na `loopTask`. Odczyt napięcia baterii (ADC+dzielnik): poniżej progu pomiń Wi-Fi, a niski stan wyślij do RX (np. bit w `validReadings`). |
| **W10** | **Parowanie bez uwierzytelnienia.** `_lastKnownMac` żyje tylko w jednym wybudzeniu; pierwsze discovery przyjmuje ACK `packetId==0` **albo dowolny pakiet innego rozmiaru** od dowolnego urządzenia na kanale 1 (gałąź „broadcast od odbiornika” – RX nigdy nic takiego nie wysyła). Obcy nadajnik ESP-NOW może „podpiąć” TX; potem filtr MAC blokuje prawdziwy RX do końca wybudzenia. RX z kolei traktuje każdy 10-bajtowy pakiet jako pomiar. | Zapisz MAC RX w RTC/flash (lub stała w `config.h`), wysyłaj unicastem bez discovery, akceptuj ACK tylko od tego MAC; usuń gałąź „nieznany pakiet”; RX: filtr MAC TX + bajt magic/CRC w pakiecie (albo szyfrowanie ESP-NOW PMK/LMK). |
| **W11** | **RX: `while(1) delay(1000)`** przy błędzie `esp_now_init` – urządzenie na ścianie zostaje martwe do ręcznego restartu; `display.begin()` zawsze zwraca true (awaria ILI9341 niewykryta). | `ESP.restart()` po 10 s (z licznikiem prób w RTC); sprawdzenie ID wyświetlacza (kod już czyta 0xD3). |
| **W12** | **GPIO23 w deep sleep [sprzęt].** `TX/AGENTS.md` twierdzi, że nie da się go podtrzymać (nie jest pinem RTC). Dokumentacja ESP-IDF opisuje `gpio_hold_en()` + `gpio_deep_sleep_hold_en()` dla pinów cyfrowych ESP32. Jeśli bramka MOSFET „pływa”, czujnik może zostać zasilony przez całą noc. | Zmierz prąd uśpienia; fizycznie pull-down 100 kΩ na bramce (już w TODO) **oraz** `gpio_hold_en(GPIO_NUM_23)` przed snem i `gpio_hold_dis` po starcie. |
| **W13** | **Logi: brak wznawiania w środku rekordu.** TX zawsze zaczyna rekord od porcji 0; przy ~18 porcjach/rekord i stratach ≥30 %/kierunek rekord praktycznie nie przechodzi (C2: 20 % → 29 wybudzeń do opróżnienia kolejki, 30 % → 100 % po 200 wybudzeniach, 50 % → 0 %). Retransmisje MAC ESP-NOW zwykle maskują to w praktyce [sprzęt]. | RX w ACK/RESTART zwraca `nextSeq`, TX wznawia od niego; ewentualnie skróć rekord (60 linii próbek ≈ 3–5 KB). |
| **W14** | **RX: wyścigi bez blokad.** `_receivedData` kopiowany w `loop()` podczas zapisu w callbacku (rozerwany odczyt), pojedynczy slot `_pendingSend` nadpisywany przy dwóch pakietach w jednej iteracji, flagi `volatile` zamiast barier. | Kolejka FreeRTOS (`xQueueSend` w callbacku, odbiór w `loop()`) dla pakietów pomiaru i porcji logu. |
| **W15** | **Reprodukowalność builda.** `platform = espressif32` i `lib_deps ^` bez przypięcia wersji – aktualizacja PlatformIO może zmienić zachowanie (LittleFS/Wi-Fi/ESP-NOW API). | Przypnij `platform = espressif32@<wersja z działającego builda>` i dokładne wersje Adafruit GFX/ILI9341; zachowaj `pio pkg lock`/`platformio.lock`. |
| **W16** | **Start z pełnym zbiornikiem (bootstrap):** przy braku odniesienia i poziomie <25 cm strefa martwa nigdy się nie włączy (wymaga `_ref.valid`), TX milczy. | Przy `!valid` i ≥80 % „<25” po 3 cyklach wyślij 25,0 z flagą. |
| **W17** | **Dokumentacja:** `TX/AGENTS.md` zawiera nieaktualne fragmenty (tabela „strefa martwa po 3 cyklach” – w kodzie 6; `RefState.cyclesSinceRef` – w kodzie `secondsSinceRef`; opis `/log.txt`). | Zaktualizuj po wdrożeniu poprawek. |

---

## 4. Co zweryfikowano jako odporne (PASS)
* **TX nie wisi:** wszystkie pętle ograniczone; najdłuższe wybudzenie 190–199 s przy RX wyłączonym, stratach 70 %/95 % i ślepym czujniku (B5).
* **Reset/utrata zasilania w środku pomiaru:** kolejny cykl 85 s później zwraca poprawną wartość (ref odtworzony z `/ref.bin`) (B4); **uszkodzony `meta.bin`** → nowa epoka, logi nadal docierają (B4b).
* **Okres cyklu** 6,04 h; sekwencje ponowień nie zachodzą na cykl regularny (B1/B2b); po powrocie RX dane wracają w ≤0,3 h.
* **Protokół logów:** kolejność i brak duplikatów przy stratach ≤20 %/kierunek; treść bajt w bajt; restart RX w połowie rekordu; pełny dysk RX nie blokuje TX; zmiana epoki; budżet 20 s dotrzymany (C1–C9).
* **RX:** NaN/Inf/ujemne/ogromne pakiety odrzucane; przywracanie wieku po utracie zasilania (zapis co 1 h, czas bez zasilania nie liczy się – udokumentowane); ekran ostrzeżenia 25–31 h po ostatnim pomiarze (D4).
* **Pomiary:** 50 % timeoutów, 80 % losowych próbek, dwa równe klastry (brak zgadywania), dominujące fałszywe echo 25,4 przy bootstrapie – wszystko obsłużone poprawnie (A3, A4, A9, A10).

## 5. Kolejność wdrożenia (propozycja)
1. **W2** (1 linia, RX) · **W1b** (RX `NO_DATA_TIMEOUT` 43 h – 1 stała) · **W4** (uint64 czas) – szybkie i bezpieczne.
2. **W3** (energia przy awarii RX) + **W9** (watchdog) + **W12** (stan MOSFET) – ochrona baterii.
3. **W5** (2-cyklowe potwierdzenie wywozu) i **W1c/W16** (flaga „podejrzenie pełnego”) – po zmierzeniu zachowania czujnika w strefie martwej.
4. **W10/W14/W11** – twardnienie komunikacji i RX.
5. **W6** (regresja) · **W8** (temperatura) · **W13** (wznawianie logów) · **W15/W17** (porządki).
Po każdej zmianie: zaktualizuj port w `Symulacje/fw` i uruchom `python run_all.py` – testy z `FAIL` mają przejść, reszta nie może się cofnąć. Jeśli chcesz, następnym krokiem może być środowisko `[env:native]` w PlatformIO kompilujące prawdziwe `measurement.cpp` z atrapami, żeby testy nie zależały od portów.
