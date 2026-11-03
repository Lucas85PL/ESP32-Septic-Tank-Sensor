# ESP32 TX 2.0.0 - Dokumentacja Projektu

> **Wersja 2.2.0** (historia pomiarów w pakiecie: patrz "Historia Zmian -> v2.2.0"; baza: v2.1.0 — odporność, v2.0.0) = TX 1.4.9 (logika V3, v1.7.2) po przeglądzie kodu + logi przez odbiornik (szczegóły: Historia Zmian → v2.0.0).
> Odbiornik w parze: `../RX 2.0.0` (RX 2.2.0 — **wgrywać OBA**, nowy format pakietu pomiaru). Folder `backup_src_v1.6.0_TX1.4.7/` z poprzedniego projektu nie został skopiowany.

## Opis Projektu
Transmiter pomiarów odległości dla płytki ESP32 z czujnikiem ultrasonicznym JSN-SR04T.

## Struktura Plików

| Plik | Opis |
|------|------|
| `src/config.h` | Wszystkie stałe konfiguracyjne (piny, timery, ustawienia) |
| `src/ultrasonic_sensor.h/cpp` | Sterownik czujnika JSN-SR04T |
| `src/measurement.h/cpp` | Logika pomiarów V3 (klastry próbek, okno czasowe, strefa martwa) |
| `src/ref_store.h/cpp` | Trwały zapis odniesienia w LittleFS (`/ref.bin`) |
| `src/espnow_manager.h/cpp` | Komunikacja ESP-NOW, automatyczne wykrywanie odbiornika |
| `src/power_manager.h/cpp` | Deep sleep i wybudzanie |
| `src/event_logger.h/cpp` | Trwały log: ostatnie 28 cykli, plik na cykl (`/c<ID>.txt`), `/meta.bin` (epoch, ID, wysłane) |
| `src/log_sync.h/cpp`, `src/log_protocol.h` | Wysyłka logów TX → RX przez ESP-NOW (porcje z ACK) |
| `src/meas_history.h/cpp` | Historia do 14 zatwierdzonych pomiarów (RTC + `/hist.bin`), czyszczona przy wzroście (wywóz); budowa pakietu z historią |
| `src/meas_protocol.h` | Pakiet pomiaru z historią `MeasurementPacketV2` (magic 0xA9) — **identyczny plik w projekcie RX** |
| `src/main.cpp` | Główny program |
| `partitions/logger_512k.csv` | Tabela partycji flash (512 KB na logi) |

## Konfiguracja Hardware

| Element | Pin ESP32 |
|---------|-----------|
| TRIG (czujnik) | GPIO 5 |
| ECHO (czujnik) | GPIO 18 |
| Gate MOSFET (zasilanie sensora) | GPIO 23 |

## Workflow Programu

```
1. START (zasilanie / wybudzenie z deep sleep)
      ↓
2. GPIO 23 → HIGH (MOSFET ON — zasilanie sensora)
      ↓
3. Serial 115200 baud
      ↓
4. LittleFS mount (log + odniesienie + meta); BRAK lokalnego dumpu logu na Serial
      ↓
5. Inicjalizacja czujnika ultrasonicznego
      ↓
6. Wyszukanie odbiornika przez ESP-NOW
      ↓
7. POMIARY (6 serii × 10 pomiarów, co 20 s) — logika V3 (TX 2.0.0):

   POZIOM 1 - Klasyfikacja odczytu: poprawny (25-170 cm) / poniżej 25 (strefa martwa) /
              powyżej 170 / timeout (zliczane osobno)

   POZIOM 2 - Konsensus na poziomie PRÓBEK (klastry):
   - Wszystkie poprawne próbki cyklu (do 60) trafiają do jednej puli (z numerem serii)
   - Szukamy najgęstszych okien o szerokości 3 cm (±1.5 cm), do 3 klastrów
   - Klaster musi mieć >= 12 próbek (POOL_MIN_SAMPLES)
   - Zepsute serie i błędne próbki rozpraszają się po zakresie i nie tworzą klastra

   POZIOM 3 - Wybór klastra:
   - Gdy jest odniesienie: największy klaster ZGODNY z oczekiwanym zakresem (okno czasowe/wywóz)
   - W przeciwnym razie największy klaster, o ile ma >= 1.5× próbek więcej niż drugi
   - validReadings = liczba serii z >= 3 próbkami w klastrze, skalowana do 0-10

   POZIOM 4 - Strefa martwa (brak klastra):
   - >= 50% próbek < 25 cm i poprzedni wynik <= 70 cm → po 6 kolejnych cyklach (36 h)
     wysyłane jest 25.0 cm; wcześniej brak wysyłki
   - W przeciwnym razie NO_VALID: nic nie wysyłamy

   POZIOM 5 - Walidacja między cyklami (zależna od CZASU od ostatniej aktualizacji):
   - Napełnianie (spadek odległości): dozwolone do 15 cm/dobę × czas + 5 cm
   - Wzrost odległości: <= 5 cm (szum) albo wynik >= 140 cm (wywóz) — wywóz po 2 kolejnych zgodnych cyklach (±10 cm) albo od razu po fizycznym resecie TX
   - Zmiana poza oknem → odrzucenie; po 4 odrzuconych cyklach z rzędu (24 h) akceptacja
     i reset odniesienia
   - Odniesienie (RefState) w RTC i we flash (/ref.bin) — zapisywane przy akceptacji pomiaru,
     NIEZALEŻNIE od ACK; po resecie/utracie zasilania odtwarzane z flash (okno +2 cykle)
      ↓
8. WYSYŁKA ESP-NOW (3 próby + 2× rediscovery):
   [brak ACK → ponawianie po 30, 30, 30, 60, 60, 120, 120 min; przy każdym ponowieniu świeży pomiar,
    jeśli odbiornik odpowiada; ponawianie kończy się przed kolejnym cyklem 6 h]
      ↓
9. Zapis rekordu cyklu do /c<ID>.txt (LittleFS, 28 ostatnich)
   [przy awarii: pełny log serii w pliku]
   [wysyłka niewysłanych cykli do odbiornika (RX) — logi czyta się z RX]
      ↓
10. GPIO 23 → LOW (MOSFET OFF — sensor bez zasilania)
      ↓
11. DEEP SLEEP (6 godzin; krótsze przerwy przy ponawianiu wysyłki)
      ↓
   [powrót do kroku 1]
```

### Montaż czujnika
TX wysyła **surową odległość** od czujnika. Korekta wysokości montażu, poziom „pełny” i „pusty” ustawia się w RX (`SENSOR_HEIGHT_OFFSET`, `MIN_DISTANCE`, `MAX_DISTANCE` w `RX/src/config.h`). Progi TX są w raw i zależą od zbiornika: `MIN_VALID_DISTANCE` 25 = strefa martwa czujnika, `EMPTY_ZONE_MIN` 140 (wzrost odległości powyżej tej wartości = wywóz; ustaw kilkanaście cm poniżej odległości do pustego zbiornika), `MAX_VALID_DISTANCE` 170 (głębiej niż dno zbiornika).

## Zmiana Konfiguracji

Edytuj plik `src/config.h`:

```c
// Piny
#define PIN_TRIG 5        // Pin TRIG czujnika
#define PIN_ECHO 18       // Pin ECHO czujnika
#define PIN_MOSFET 23     // Gate MOSFET (zasilanie sensora)

// Czas deep sleep
#define DEEP_SLEEP_SECONDS 21600  // 6 godzin

// Pomiary
#define SERIES_COUNT 6            // Liczba serii (6)
#define MEASUREMENTS_PER_SERIES 10 // Pomiarów na serię (10)
#define SERIES_INTERVAL_MS 20000  // Odstęp między seriami (20s)
#define MEASUREMENT_INTERVAL_MS 1000 // Odstęp między pomiarami (1s)

// Zakres pomiarów
#define MIN_VALID_DISTANCE 25.0f   // Minimalna prawidłowa odległość
#define MAX_VALID_DISTANCE 170.0f  // Maksymalna prawidłowa odległość

// Klastry próbek
#define POOL_HALF_WIDTH_CM 1.5f
#define POOL_MIN_SAMPLES 12
#define POOL_DOMINANCE_RATIO 1.5f
#define POOL_MAX_CLUSTERS 3
#define POOL_SERIES_MIN_SAMPLES 3

// Walidacja między cyklami (zależna od czasu)
#define FILL_MAX_CM_PER_DAY 15.0f
#define RISE_NOISE_CM 5.0f
#define EMPTY_ZONE_MIN 140.0f
#define MAX_REJECTED_CYCLES 4   // 24 h

// Strefa martwa (< 25 cm)
#define DEADZONE_MIN_RATIO_PCT 50
#define DEADZONE_LAST_MAX_CM 70.0f
#define DEADZONE_CONFIRM_CYCLES 6   // 36 h

// Ponawianie wysyłki po braku ACK
#define SEND_RETRY_COUNT 7
static const uint32_t SEND_RETRY_SCHEDULE_S[] = {1800, 1800, 1800, 3600, 3600, 7200, 7200};

// Odniesienie we flash
#define REF_FILE_PATH "/ref.bin"
#define REF_RESTORE_EXTRA_SECONDS 86400UL

// Event Logger (LittleFS)
#define LOG_PARTITION_LABEL     "spiffs"
#define LOG_KEEP_CYCLES         28     // ostatnie 28 cykli (plik na cykl)
#define LOG_SYNC_BUDGET_MS      20000  // limit czasu wysyłki logów do RX
#define LOG_SESSION_BUFFER_SIZE 8192
```

## Partycja flash i LittleFS

Projekt używa niestandardowej tabeli partycji `partitions/logger_512k.csv`:

| Partycja | Rozmiar | Zawartość |
|----------|---------|-----------|
| app0 | ~1.6 MB | Firmware |
| spiffs | 512 KB | LittleFS — pliki `/c<ID>.txt`, `/meta.bin`, `/ref.bin` |

Konfiguracja w `platformio.ini`:
```
board_build.partitions = partitions/logger_512k.csv
board_build.filesystem = littlefs
monitor_rts = 0
monitor_dtr = 0
```

**Uwaga:** `pio run -t upload` wgrywa tylko firmware — **logi na LittleFS przetrwają** upload.
Aby skasować logi: `pio run -t erase` (czyści cały flash) lub ręczny format przy błędzie mount.

## Logi diagnostyczne (v2.0.0)

### Przechowywanie na TX
- Każdy cykl (każde wybudzenie z pomiarem, także ponowienie wysyłki) to osobny plik `/c<ID>.txt` na LittleFS:
  linia skrótu + pełny log sesji (próbki, klastry, decyzje, wynik wysyłki). **Zawsze**, nie tylko przy awarii.
- Przechowywane jest **ostatnie 28 rekordów** (`LOG_KEEP_CYCLES`); starsze są kasowane (brak kopiowania/rotacji pliku).
- `ID` rośnie monotonicznie i jest trwały (`/meta.bin`); razem z `epoch` (losowa wartość nadana przy utworzeniu
  `meta.bin`, zmienia się po pełnym `erase`) tworzy unikalny identyfikator rekordu.
- Przy braku miejsca (`LOG_MIN_FREE_BYTES`) kasowane są najstarsze rekordy — log nigdy nie blokuje pomiarów.
- Pierwsze uruchomienie po aktualizacji ze starej wersji: stary `/log.txt` jest usuwany.

### Wysyłka TX → RX (ESP-NOW)
Po wysłaniu pomiaru (i zapisaniu cyklu) TX wysyła do odbiornika wszystkie niewysłane rekordy (`src/log_sync.cpp`,
protokół `src/log_protocol.h` — **plik identyczny w projekcie RX**):
- rekord dzielony na porcje 224 B, każda potwierdzana przez RX (stop-and-wait, 3 próby × 300 ms),
- rekord uznawany za wysłany dopiero po potwierdzeniu ostatniej porcji (`sentId` w `/meta.bin`) — przerwana
  wysyłka jest wznawiana przy następnym wybudzeniu; RX odrzuca duplikaty (epoch + id),
- limit czasu `LOG_SYNC_BUDGET_MS` (20 s) na wybudzenie; brak odbiornika = brak strat energii (pierwsza porcja bez ACK kończy próbę).

### Odczyt na laptopie (przez odbiornik)
1. Zamknij PlatformIO Monitor (port COM może mieć jednego użytkownika).
2. W projekcie RX: `python tools/txlog_pobierz.py` → plik `logi_tx/txlog_<data>.txt` (na ekranie tylko podsumowanie).
   Opcje: `--last N`, `--out plik.txt`, `--clear`, `--port COM5`.
3. Ręcznie z Monitora RX: `TXLOG` (info), `TXLOG DUMP`, `TXLOG CLEAR`.

### Brak lokalnego dumpu
TX **nie ma** już dumpu logu na Serial ani odliczania przed nim — jedyna droga odczytu to odbiornik (patrz wyżej).
Serial Monitor TX pokazuje tylko bieżące komunikaty cyklu.

### Reset zasilania (odłączenie/włączenie baterii)
Bezpieczny w każdej chwili: RTC się zeruje, ale odniesienie (`/ref.bin`, zapisywane przy każdym pomiarze z jego wiekiem),
licznik cykli i stan wysyłki (`/meta.bin`) są we flash. Po starcie TX od razu wykonuje cykl pomiarowy, okno napełniania
jest poszerzone o 24 h (`REF_RESTORE_EXTRA_SECONDS`), a niewysłane logi dochodzą do RX przy następnym kontakcie.
Przerwanie zasilania w trakcie zapisu: rekord pisany przez plik `.tmp` + rename, uszkodzone `meta.bin`/`ref.bin` są wykrywane
sumą kontrolną (meta: nowa epoka i ponowna wysyłka rekordów; ref: bootstrap przy pierwszym wiarygodnym cyklu).
Przyczyna startu (`WAKE=TIMER|POWERON|BROWNOUT|PANIC|...`) jest w linii skrótu każdego cyklu.

### Format rekordu
```
CYCLE=57 | WAKE=TIMER | valid=1 | result=67.41 | series=5/6 | send=OK
--- SESSION CYCLE=57 BEGIN | WAKE=TIMER | ref=67.41 ---
[CYKL] ... [SERIA 1/6] ... [POMIAR] 1: 67.55 cm ... [KLASTER] ... [WYNIK] ... [MAIN] Wysylka OK ...
--- SESSION CYCLE=57 END ---
```
W pliku na laptopie przed każdym rekordem RX dopisuje `##### RX epoch=XXXXXXXX id=57 bytes=N`.

## Kompilacja i Wgrywanie

### W VS Code:
1. Otwórz projekt
2. Kliknij ikonę PlatformIO (alien) w lewym panelu
3. Rozwiń `esp32dev` → `General`
4. Kliknij `Upload` (strzałka w prawo)

### Lub przez terminal VS Code:
```
pio run -t upload
```

## Podgląd Serial Monitor (tylko bieżące komunikaty — bez dumpu logu)

1. Podłącz ESP32 przez USB
2. Otwórz Monitor i naciśnij RESET (komunikaty cyklu pojawią się od razu — nie ma już odliczania)
3. W VS Code: `PlatformIO` → `Monitor`
4. Lub terminal: `pio device monitor`
5. Baud rate: **115200**
6. Krzaczki na początku = bootloader (74880 baud) — ignoruj, czekaj na `[LOG]` lub nagłówek TX

## Wynik pomiaru - struct MeasurementResult

```cpp
enum class CycleStatus : uint8_t { OK, BELOW_MIN_RANGE, NO_VALID, REJECTED_JUMP };

struct MeasurementResult {
    float value;                    // wynik pomiaru [cm]
    bool isValid;                   // czy wysyłamy wynik
    CycleStatus status;
    uint8_t acceptedSeriesCount;    // ile serii zgodnych w konsensusie (w pakiecie skalowane do 0-10)
};

struct RefState {                   // RTC_DATA_ATTR, przeżywa deep sleep
    float value; bool valid; uint32_t secondsSinceRef;
    uint8_t rejectedCycles; uint8_t deadzoneCycles;
    uint8_t risePending; float riseValue;   // kandydat na wywoz czekajacy na potwierdzenie (v2.1.0)
};
```

Format pakietu ESP-NOW (`MeasurementPacket`) i kod odbiornika pozostają bez zmian.
`validReadings` jest zawsze w skali 0-10 (`LEGACY_VALID_READINGS_SCALE`), niezależnie od `SERIES_COUNT`.

### Przykładowe wyniki (v2.0.0):

| Scenariusz | status | wysyłka |
|------------|--------|---------|
| Normalny pomiar | OK | tak, wynik cyklu |
| Wywóz (158-162 cm, >= 140) | OK | tak |
| Duży błąd czujnika / wyjęty czujnik (brak konsensusu) | NO_VALID | nie |
| Zmiana poza oknem czasowym (1-2 cykle) | REJECTED_JUMP | nie |
| Poziom < 25 cm przez 6 kolejnych cykli (36 h) | BELOW_MIN_RANGE | tak, 25.0 cm |
| Wywoz (>=140 cm) w 1. cyklu | REJECTED_JUMP (oczekuje) | nie; 2. zgodny cykl albo reset TX -> OK |

## Testowanie

### Test samego czujnika:
W `main.cpp` zakomentuj ESP-NOW i deep sleep, zostaw tylko pomiary + Serial.println wyników.

### Test ESP-NOW:
1. Uruchom odbiornik (musi nadawać broadcast)
2. Włącz transmiter
3. Obserwuj "[ESP-NOW] Wykryto odbiornik!"

## Zachowanie przy braku komunikacji z odbiornikiem

### Brak wykrycia odbiornika (etap discovery):
- Transmiter szuka odbiornika przez **10 sekund**
- Jeśli nie znajdzie → kontynuuje pomiary → próbuje wysłać → idzie spać

### Brak potwierdzenia ACK (etap wysyłki):
- **3 próby** wysyłki, każda z timeout 2s na ACK
- Odstęp między próbami: 1 sekunda
- **Czas całkowity: ~9 sekund**
- Po 3 nieudanych próbach → **deep sleep** → ponowna próba za 6 godzin

| Scenariusz | Wynik |
|------------|-------|
| Odbiornik odpowiada | Dane wysłane → ACK → deep sleep |
| Odbiornik nie odpowiada | 3 próby (~9s) → deep sleep → ponowna próba za 6h |

**Decyzja:** Idź spać niezależnie od wyniku - oszczędność baterii.

## Czasy Wykonywania Pomiarów

### Konfiguracja (v2.0.0)
| Parametr | Wartość |
|----------|---------|
| Liczba serii | 6 |
| Pomiarów na serię | 10 |
| Odstęp między pomiarami | 1 sekunda |
| Odstęp między seriami | 20 sekund |
| Deep sleep | 6 godzin (30 min po nieudanej wysyłce) |

Cykl pomiarowy trwa ok. 2,7 min (poprzednio ok. 11 min).

---

## Analiza Scenariuszy i Znane Ograniczenia (historyczna — logika v1.5.0)

> **Od v1.6.0 PROBLEM-A/B/C i PLAN-1/2/3 są zastąpione nową logiką (konsensus serii + okno czasowe + zapis odniesienia niezależnie od ACK). Wyniki porównania starej i nowej logiki: `symulacja/wyniki.md`.**

> Analiza przeprowadzona 2026-04-12 przy założeniu: `lastAcceptedValue = 61cm`, `lastValueValid = true`.
> Stałe: `FILL_THRESHOLD_SMALL = 5cm`, `FILL_THRESHOLD_LARGE = 15cm`, `EMPTY_ZONE_MIN = 130cm`, `MAX_VALID_DISTANCE = 170cm`.

### Wyniki analizy

| # | Scenariusz | Wynik | Ocena |
|---|------------|-------|-------|
| 1 | Pojedynczy pomiar 15cm w serii (reszta ~61cm) | 15cm odfiltrowane przez zakres, seria daje ~61cm | OK |
| 1b | Cała seria to 15cm | Seria pominięta (0 prawidłowych pomiarów), pozostałe serie OK | OK |
| 2 | Cała seria daje 170cm (błąd sensora) | SUSPICIOUS_EMPTY → retry 170cm → **ACCEPT** → utknięcie na 170cm | **PROBLEM** |
| 3 | Kilka serii z pomiarem 14cm | 14cm odfiltrowane przez zakres (< 25cm), bez wpływu | OK |
| 4 | Kilka serii z pomiarem 170cm | Seria 1: SUSPICIOUS_EMPTY → ACCEPT; kolejne: delta≈0 → ACCEPT; powrót do 61cm niemożliwy | **PROBLEM** |
| 5 | Reset, woda nadal 61cm | Bootstrap (v1.4.4) → seria 1 zaakceptowana bezwarunkowo | OK |
| 6 | Reset, woda zmieniła się 61→45cm | Bootstrap → seria 1 przyjmuje 45cm | OK |
| 7 | Reset, zbiornik pusty (170cm) | Bootstrap → seria 1 przyjmuje 170cm | OK |
| 8 | Wyjęcie czujnika (mierzy 30cm), potem włożenie do pustego zbiornika | Fase 1: 30cm → SUSPICIOUS_FILL → fallback, serie odrzucane; Faza 2: 170cm → SUSPICIOUS_EMPTY → retry → ACCEPT | OK |
| 8b | Wyjęcie czujnika, mierzy przypadkowo 130–170cm | SUSPICIOUS_EMPTY → retry potwierdza → **ACCEPT jako fałszywe opróżnienie** | **PROBLEM** |

### Zidentyfikowane problemy

#### PROBLEM-A — Fałszywe przyjęcie 170cm i brak powrotu (scenariusze 2, 4)

Algorytm nie ma górnego progu dla skoku opróżnienia. Skok 61→170cm (+109cm) jest traktowany
identycznie jak rzeczywiste opróżnienie zbiornika. Po przyjęciu 170cm jako `_lastAcceptedValue`
powrót do 61cm jest niemożliwy — każda seria z 61cm generuje delta = -109cm (SUSPICIOUS_FILL),
retry potwierdza → fallback. Urządzenie pozostaje zablokowane na 170cm aż do resetu.

**Sytuacje wyzwalające:** błąd sensora dający stabilnie ~170cm przez ≥ 2 serie; chwilowa
przeszkoda w zakresie 130–170cm podczas opróżniania.

#### PROBLEM-B — Czujnik wyjęty przypadkowo mierzy 130–170cm (scenariusz 8b)

Czujnik wyjęty z wody może przypadkowo mierzyć odległość do ściany/podłogi ≥ 130cm.
`EMPTY_ZONE_MIN = 130cm` to jedyne kryterium odróżniające prawdziwe opróżnienie od błędu —
jeśli czujnik trzymany w ręku mierzy np. 150cm, retry potwierdza 150cm i seria jest akceptowana
jako prawdziwe opróżnienie. Kolejne serie z prawdziwym 61cm będą odrzucane (SUSPICIOUS_FILL).

Dotyczy szczególnie opisanego przypadku użycia: czujnik jest wyjmowalny na czas opróżniania
i w tym czasie może mierzyć przypadkowe wartości.

#### PROBLEM-C — Asymetria: prawdziwe napełnienie > 15cm zawsze odrzucane

W `handleSuspiciousFill` warunek akceptacji retry: `delta >= 0 OR |delta| <= 15cm`.
Napełnienie zbiornika o ponad 15cm w ciągu jednego cyklu (12h) jest zawsze odrzucane jako błąd
czujnika — nawet jeśli fizycznie możliwe. Znany trade-off, niekoniecznie błąd.

---

### Planowane poprawki (nieimplementowane)

#### [PLAN-1] Próg maksymalnego skoku opróżnienia (`EMPTY_MAX_DELTA`)

Dodać stałą `EMPTY_MAX_DELTA` (np. 120cm). Skok opróżnienia przekraczający ten próg traktować
jak IMPOSSIBLE_EMPTY — fallback bez retry. Uzasadnienie: w ciągu jednego cyklu pomiarowego
(10–11 min) zbiornik nie może opróżnić się o więcej niż fizycznie możliwe tempo odpływu.

Pliki: `config.h` (nowa stała), `measurement.cpp` (warunek w `validateDirectional()`).

```
// Przykładowe progi
EMPTY_ZONE_MIN    = 130cm   // poniżej: opróżnienie niemożliwe (bez zmian)
EMPTY_MAX_DELTA   = 120cm   // powyżej: skok zbyt duży nawet dla prawdziwego opróżnienia
```

#### [PLAN-2] Wymaganie spójności przez N serii przed akceptacją dużego skoku

Zamiast akceptować duży skok opróżnienia po 1 retry (2 serie łącznie), wymagać potwierdzenia
przez N kolejnych niezależnych serii (np. 3). Zwiększa odporność na błędy sensora kosztem
wolniejszej reakcji na prawdziwe zdarzenia.

Pliki: `measurement.h` (licznik pending), `measurement.cpp` (logika akumulacji).

#### [PLAN-3] Detekcja "wyjętego czujnika" przez analizę wzorca pomiarów

Czujnik wyjęty z wody zazwyczaj generuje niestabilne, losowe odczyty (duże MAD) lub wartości
spoza typowego zakresu operacyjnego. Można dodać heurystykę: jeśli MAD serii jest znacząco
wyższe niż w poprzednich seriach → podejrzenie wyjętego czujnika → fallback bez retry.

Pliki: `measurement.h` (historia MAD), `measurement.cpp` (porównanie MAD).

---

## Historia pomiarów w pakiecie (v2.2.0)

TX trzyma do 14 ostatnich **zatwierdzonych** pomiarów (`meas_history.cpp`) i wysyła je razem z bieżącym pomiarem w `MeasurementPacketV2` (`meas_protocol.h`, ok. 111 B, magic 0xA9). RX odtwarza z niego oś czasu i prognozę „Pełny za”, więc nie potrzebuje własnej historii (restart / wymiana RX / utrata pakietów nie kasują prognozy).

- **Punkt historii:** surowa odległość + wiek [s] + flaga sztucznego 25.0 cm (strefa martwa; RX nie liczy go do regresji). Dodawany po każdym zaakceptowanym pomiarze (`MeasHistory::onAccepted` w `performMeasurement`). Świeży pomiar przy ponowieniu wysyłki zastępuje punkt tego samego cyklu (ten sam `seq`).
- **Numeracja:** `seq` rośnie o 1 na każdy zatwierdzony pomiar (punkt *i* w pakiecie ma numer `seq - i`) i jest trwały. `epoch` = losowy identyfikator „życia” historii, tworzony gdy brak/uszkodzony `/hist.bin` (wtedy `seq` od 0; RX rozpoznaje zmianę epoki). `packetId` nadal służy tylko do ACK.
- **Czyszczenie:** historia jest kasowana przy zaakceptowanym wzroście odległości (> `RISE_NOISE_CM`: wywóz) oraz przy resecie odniesienia po `MAX_REJECTED_CYCLES` odrzuconych cyklach. **Sam reset TX historii nie czyści** (utrata zasilania w trakcie napełniania nie kasuje prognozy). Po fizycznym resecie pierwszy pomiar ≥140 cm jest przyjmowany od razu → historia czyszczona → RX dostaje 1 punkt.
- **Pamięć:** RTC (`RTC_DATA_ATTR`, przeżywa deep sleep) + `/hist.bin` (LittleFS, zapis atomowy `.tmp` + rename, suma kontrolna FNV; uszkodzony plik = nowa epoka). Po resecie zasilania wiek najnowszego punktu jest nieznany — zakładane `HIST_ASSUMED_GAP_S` = 3 h (pół okresu); krótkie zaniki nie psują prognozy.
- **Strefa martwa:** przy fizycznym resecie TX licznik `deadzoneCycles` jest zerowany (czujnik wyjmowany na < 30 h nie wysyła sztucznego 25.0; symulacja: 30 h → 0/12 przypadków, 36 h → 7/12, 42 h → 10/12).
- `RTC_STATE_MAGIC` 0x52544333 (zmiana układu RTC) — pierwszy start po wgraniu = czysty stan RTC.
- Weryfikacja: symulacja `../Symulacje/` (testy G, 75 PASS); **kod C++ nie był kompilowany na tej maszynie — zrób `pio run` przed wgraniem**.

## Historia Zmian

### 2026-10-18 - v2.2.0 (historia pomiarów w pakiecie; para z RX 2.2.0 — wgrywać OBA)
- Nowe: `meas_history.h/cpp`, `meas_protocol.h` (identyczny w RX), plik `/hist.bin` we flash.
- `espnow_manager`: `sendBuffer()` (wspólna wysyłka + ACK po `packetId`), `sendMeasurementWithRetry(MeasurementPacketV2&, len)`; discovery nadal w starym `MeasurementPacket` (10 B).
- `main.cpp`: `MeasHistory::advanceClock/begin` po zamontowaniu LittleFS, `onAccepted` po zaakceptowanym pomiarze, pakiet V2 w `sendValue`, zerowanie licznika strefy martwej przy fizycznym resecie.
- `config.h`: `FW_VERSION` 2.2.0, `HIST_FILE_PATH`, `HIST_ASSUMED_GAP_S`, `RTC_STATE_MAGIC` 0x52544333.

### 2026-10-11 - v2.1.0 (odpornosc; para z RX 2.1.0)
- **Energia przy awarii odbiornika:** brak ponownego discovery gdy odbiornik nieznany; po `FAILED_CYCLES_NO_RETRY` (1) nieudanym cyklu brak wybudzen na ponowienia (RTC `failedRegular`). Symulacja: ~1,2x normy zamiast ~6,5x.
- **Czujnik wlaczany tuz przed pomiarem** (MOSFET LOW na starcie wybudzenia), takze przy ponowieniach.
- **Wywoz:** wzrost odleglosci do >=140 cm przyjmowany po 2 kolejnych zgodnych cyklach (`RISE_CONFIRM_TOL_CM` 10) albo od razu po fizycznym resecie TX (odlaczenie zasilania / EN). `RefState.risePending/riseValue`.
- **Bezpiecznik czasowy** `WATCHDOG_TIMEOUT_MS` (10 min, esp_timer): MOSFET OFF + deep sleep; wpis w logu przy nastepnym starcie. `RTC_STATE_MAGIC` - czysty stan RTC po wgraniu nowej wersji.
- **Logi:** wznawianie przerwanego rekordu (`LogAckPacket.nextSeq`, punkt wznowienia w RTC; `log_protocol.h` zmieniony - identyczny w RX).
- `platformio.ini`: `platform = espressif32@7.1.3`.
- Poprawiona nieaktualna dokumentacja (strefa martwa = 6 cykli, `secondsSinceRef`, pliki `/c<ID>.txt`).
- Swiadomie BEZ zmian (decyzja uzytkownika): potwierdzenie strefy martwej 36 h vs alarm RX 25 h (wywoz organizowany wczesniej), parowanie bez uwierzytelnienia, brak pomiaru baterii/temperatury.

### 2026-10-11 - v2.0.0 (przegląd kodu + logi przez odbiornik; dawniej TX 1.4.9 / v1.8.0)
- **Cykl pomiarowy co 6 h** (`DEEP_SLEEP_SECONDS 21600`); progi czasowe zachowane: `MAX_REJECTED_CYCLES` 4 (24 h), `DEADZONE_CONFIRM_CYCLES` 6 (36 h). Retencja 28 cykli = 7 dni. Harmonogram ponowień (łącznie 7,5 h) jest ucinany przed kolejnym cyklem.
- **Kolejność:** regularny cykl = pomiar PRZED włączeniem Wi-Fi (mniejszy pobór, brak zakłóceń radiowych podczas `pulseIn`);
  czujnik wyłączany (MOSFET) po pomiarze; `SENSOR_WARMUP_MS` po starcie czujnika. Ponowienie: discovery → radio OFF → pomiar → ESP-NOW → wysyłka.
- **Wiek odniesienia w sekundach** (`RefState.secondsSinceRef`, rzeczywisty czas wybudzeń) zamiast licznika cykli;
  pomiar przy ponowieniu nie zwiększa `rejectedCycles`/`deadzoneCycles` (wcześniej 7 ponowień ≈ +3,5 doby okna i odrzucenia po ~1 h). `ref.bin` v2 (czyta też v1).
- **Logger:** plik na cykl, 28 ostatnich, trwały ID + epoch, brak kopiowania przy rotacji (stary błąd: kopia 337 KB nie mieści się w partycji 512 KB).
- **Przyczyna startu:** `esp_reset_reason()` w logu; bez lokalnego dumpu na Serial (logi tylko przez RX).
- **ACK:** sukces = ACK aplikacyjny z pasującym `packetId` (bez wyścigu z callbackiem wysyłki, spóźnione ACK ignorowane).
- **Logi TX → RX** (patrz sekcja „Logi diagnostyczne”). Odbiornik: `txlog.cpp`, komendy `TXLOG*`, `tools/txlog_pobierz.py`.
- **Sprzęt do sprawdzenia:** GPIO 23 nie jest pinem RTC — w deep sleep nie da się go podtrzymać; bramka MOSFET-a powinna mieć rezystor do masy (np. 100 kΩ).

### 2026-10-08 - v1.7.2 (wynik roju agentów: klastry z wsparciem serii)
Rój 5 agentów (`symulacja/swarm/`) + złożenie `swarm/v5.py`; test obciążeniowy 20 scenariuszy (`swarm/e_stress.py`, `swarm/v5_stress_wyniki.md`).
- Klaster zgodny z oczekiwanym zakresem przyjmowany od 6 próbek, jeśli ma próbki z >= 3 różnych serii (`POOL_PRIOR_MIN_*`); dominacja bez zmian (12 próbek)
- Wolniejsze okno napełniania (8 cm/dobę) dla wyników < 35 cm (`SLOW_FILL_*`)
- Strefa martwa wymaga rozrzutu odczytów < 25 cm >= 1,5 cm (`DEADZONE_MIN_SPREAD_CM`) i liczy okno 8 cm/dobę
- Symulacja (150 przebiegów, błędy z logu): widok dobry 90,1% -> 94,1%, fałszywe „pełny" 15% -> 0% przebiegów; bez błędów bez regresji
- Odrzucone przez rój: dodatkowe próby po ślepocie (zysk marginalny), adaptacyjne tempo napełniania, bootstrap 2-cyklowy (pogarsza), wyjście z fałszywego odniesienia (zmiana RefState, brak zysku w głównym scenariuszu)
- Znane, nienaprawione: błędy w 30-80% cykli lub 3 z 6 serii stale złych (~60 grubych błędów/50 dni), dryf czujnika, fałszywe odniesienie przy bootstrapie

### 2026-10-08 - v1.7.1 (poprawki po analizie logu z czujnika)
Analiza logu v1.5.0 (`pomiary.txt`): czujnik bywa "slepy" (cykle 11-12) lub daje stale falszywe echo ok. 25,2-25,8 cm (cykl 3),
podczas gdy poziom rosl normalnie ok. 6 cm/dobe.
- `NEAR_MIN_MARGIN_CM` (5 cm): wynik poza oknem i < 30 cm nie resetuje odniesienia (NO_VALID); okno rosnie z cyklami i samo dogoni prawdziwy poziom
- Strefa martwa (< 25 cm) liczona tylko gdy odniesienie moglo tam dojsc w oknie napelniania (`DEADZONE_PLAUSIBLE_MARGIN_CM`) - inaczej blad czujnika, nie falszywe 25,0 cm
- Zmiany tylko w `measurement.cpp/.h`, `config.h`; kompilacja `pio run`: SUCCESS

### 2026-10-04 - v1.7.0 (TX 1.4.9 - V3)
**Wynik 4 iteracji symulacyjnych (`symulacja/wyniki2.md`), start: TX 1.4.7.**

- **Klastry próbek zamiast konsensusu serii** (największy zysk: cykle bez wyniku z 26 → 3 na 100 przy ostrych błędach)
- **Wybór klastra zgodnego z oczekiwanym zakresem** (okno napełniania / wywóz)
- **Odniesienie we flash** (`/ref.bin`) — reset/utrata zasilania nie powoduje już bootstrapu na pierwszym pomiarze
- **Ponawianie po braku ACK**: 30/30/30/60/60/120/120 min ze świeżym pomiarem (powrót po awarii odbiornika: mediana 1 h zamiast 6 h)
- Usunięty MAD w serii i konsensus serii (zastąpione klastrami)
- Format pakietu ESP-NOW i odbiornik bez zmian; `validReadings` nadal w skali 0-10

Wyniki (symulacja 50 dni): widok odbiornika dobry 96.4% (1.4.7: 93.5%); w trudniejszych warunkach 91.5% (1.4.7: 49.4%).
Poprzednie źródła (TX 1.4.7): `backup_src_v1.6.0_TX1.4.7/`.

### 2026-10-04 - v1.6.0 (Nowa logika akceptacji i wysyłki — koniec blokowania)
**Problem:** nadajnik czasem przestawał wysyłać. Przyczyna: odniesienie `lastAcceptedValue` aktualizowane tylko po ACK, a każdy
cykl porównywany ze starą wartością (sprzed 12 h i więcej) z progiem 15 cm → po ok. 2 dobach bez ACK wszystkie serie były
odrzucane na stałe (do wywozu / resetu).

**Zmiany (tylko nadajnik, format pakietu bez zmian):**
- `RefState` w RTC, aktualizowany przy akceptacji pomiaru niezależnie od ACK
- Okno napełniania zależne od czasu (15 cm/dobę × czas od ostatniej aktualizacji + 5 cm)
- Reset odniesienia po 2 odrzuconych cyklach z rzędu
- Konsensus serii w cyklu zamiast sekwencyjnego porównywania z historią; min. 5 próbek na serię; dolny próg MAD 1 cm
- Wywóz: wzrost odległości akceptowany gdy wynik >= 140 cm (`EMPTY_ZONE_MIN`), bez blokad
- Strefa martwa (< 25 cm): po 3 cyklach wysyłane 25.0 cm
- Ponowna wysyłka po NO_ACK po 30 min (max 3×), bez ponownego pomiaru
- 6 serii co 20 s zamiast 10 co 60 s (cykl ok. 2,7 min zamiast ok. 11 min)
- Cykl bez wiarygodnego wyniku nie wysyła niczego (decyzja: opcja A)

**Weryfikacja:** `symulacja/sim.py` (port Python starej i nowej logiki; brak kompilatora C++ na maszynie dev —
firmware wymaga kompilacji `pio run` przed wgraniem).

### 2026-06-16 - v1.5.0 (Logger zdarzeń — LittleFS)
**Trwały log cykli pomiarowych na flash do diagnostyki awarii:**

**Nowe pliki:**
- `src/event_logger.h/cpp` — mount LittleFS, bufor sesji, zapis `/log.txt`, dump na Serial, rotacja
- `partitions/logger_512k.csv` — partycja 512 KB na filesystem

**Zmiany w istniejących plikach:**
- `platformio.ini`: partycja LittleFS, `monitor_rts/dtr = 0`
- `config.h`: stałe `LOG_*` (ścieżka, rozmiar, czas oczekiwania USB)
- `main.cpp`: dump historii na starcie, `commitSession()` przed snem, odliczanie 12 s przy `WAKE=RESET`, powtórzony dump przed snem na USB
- `measurement.h/cpp`: opcjonalny `EventLogger*` — równoległy zapis szczegółów sesji (`MEAS_LOG` / `MEAS_LOGF`)
- `power_manager.h/cpp`: `getWakeupReasonString()` — helper bez zmiany logiki sleep

**Zachowanie:**
- Sukces: 1 linia skrótu na cykl w `/log.txt`
- Awaria (`NO_VALID_SERIES`, `NO_ACK`, `ESPNOW_INIT_FAIL`): skrót + pełny log serii
- Upload firmware **nie kasuje** logów (osobna partycja flash)
- Budzenie TIMER (6 h, bateria): bez 12 s oczekiwania — oszczędność czasu

### 2026-04-12 - v1.4.4 (Bootstrap po resecie)
**Naprawa odrzucania pomiarów po hard resecie / cold boot:**

- `main.cpp`: dodano `RTC_DATA_ATTR bool lastValueValid = false;` — po resecie `false`, po pierwszym udanym pomiarze `true`; przekazywany do konstruktora `MeasurementManager`; ustawiany na `true` w `sendResult()` po udanej wysyłce
- `measurement.h`: dodano pole `bool _lastAcceptedValueValid`; zaktualizowano sygnaturę konstruktora o parametr `bool lastAcceptedValueValid = false`
- `measurement.cpp`: w `performFullMeasurementCycle()` — gdy `_lastAcceptedValueValid == false`, pierwsza seria akceptowana bezwarunkowo (bootstrap), flaga ustawiana na `true`; kolejne serie i wszystkie następne cykle działają normalnie

Powód: po resecie `lastAcceptedValue` resetuje się do `FIRST_CYCLE_FALLBACK_CM = 100cm`. Przy rzeczywistym poziomie odbiegającym od 100cm (np. 61cm) delta przekraczała `FILL_THRESHOLD_LARGE`, wszystkie serie były odrzucane jako `SUSPICIOUS_FILL`, a `lastAcceptedValue` nigdy nie było aktualizowane — urządzenie nie wykonywało żadnych pomiarów.

### 2026-03-24 - v1.4.3 (Rozszerzenie zakresu pomiarowego)
**Zwiększenie MAX_VALID_DISTANCE z 160 cm na 170 cm:**

- `config.h`: `MAX_VALID_DISTANCE` zmienione z `160.0f` na `170.0f`

Powód: dopasowanie górnej granicy zakresu do rzeczywistej głębokości pustego zbiornika.

### 2026-03-17 - v1.4.2 (MOSFET Gate Control)
**Sterowanie zasilaniem sensora przez MOSFET na GPIO 23:**

- `config.h`: dodano `#define PIN_MOSFET 23`
- `main.cpp`: `pinMode(PIN_MOSFET, OUTPUT)` + `digitalWrite(PIN_MOSFET, HIGH)` jako pierwsze instrukcje `setup()` — sensor zasilany od razu po budzeniu
- `power_manager.cpp`: `digitalWrite(PIN_MOSFET, LOW)` + `delay(10)` tuż przed `esp_deep_sleep_start()` — sensor odcięty przed każdym deep sleep (niezależnie od ścieżki: błąd ESP-NOW lub normalne zakończenie cyklu)

### 2026-03-08 - v0.5.1
**Poprawka: zignorowana wartość zwracana `initializeEspNow()` w setup():**

- `initializeEspNow()` w `setup()` — wartość zwracana była ignorowana, a sprawdzenie `isInitialized()` było redundantne
- `initializeEspNow()`: usunięto `return false` przy nieudanym discovery (discovery failure jest niekrytyczne — `trySendWithRediscovery()` ponawia próbę)
- `setup()`: zamiast `initializeEspNow()` + osobne `if (!isInitialized())` → bezpośrednie `if (!initializeEspNow())`

### 2026-03-08 - v0.5 (Audyt jakości — obecna)
**Poprawki jakościowe i bezpieczeństwo kodu po audycie:**

**measurement.cpp:**
- `MeasurementResult result = {}` — pełna inicjalizacja przez zero (TX-1)

**espnow_manager.h + espnow_manager.cpp:**
- `discoveryPacket = {}` — bezpieczna inicjalizacja przez zero (TX-2)
- Dodano `portMUX_TYPE _mux` — spinlock FreeRTOS chroniący `_state` między Core 0 (callback ESP-NOW) a Core 1 (loop). `portENTER_CRITICAL`/`portEXIT_CRITICAL` w `onDataSent`, `onDataReceived` i `sendData` (TX-3)
- Dodano `_lastKnownMac[6]` — podczas rediscovery akceptowany jest tylko poprzednio znany MAC odbiornika. Zapobiega połączeniu z losowym ESP32 (TX-4)

---

### 2026-03-08 - v0.4 (Empty Zone Validation)
**Rozszerzenie walidacji kierunkowej o kontrolę strefy opróżnienia:**

**Zmiany w config.h:**
- DODANO: `EMPTY_ZONE_MIN = 130.0f` (poniżej tej wartości opróżnienie jest fizycznie niemożliwe)
- FILL_THRESHOLD_SMALL komentarz uaktualniony (dotyczy teraz obu kierunków)

**Zmiany w measurement.h:**
- DODANO: `enum class ValidationResult { ACCEPT, SUSPICIOUS_FILL, SUSPICIOUS_EMPTY, IMPOSSIBLE_EMPTY }`
- `validateDirectional()` zmienił typ zwracany: `bool` → `ValidationResult`
- DODANO: `handleSuspiciousEmpty(float suspiciousMedian, bool& isFallback)`
- DODANO: pole `acceptedSeriesCount` w `MeasurementResult`

**Nowa logika opróżnienia (zastępuje "zawsze akceptuj"):**
- `|delta| ≤ 5cm`                          → ACCEPT (szum)
- `delta > 5cm` AND `odczyt ≥ 130cm`       → SUSPICIOUS_EMPTY → retry (1 próba)
- `delta > 5cm` AND `odczyt < 130cm`       → IMPOSSIBLE_EMPTY → natychmiastowy fallback

**Weryfikacja scenariuszy:**

| Sytuacja | lastAccepted | Odczyt | delta | Wynik |
|----------|-------------|--------|-------|-------|
| Czujnik wyciągnięty (50cm) | 40cm | 50cm | +10cm | fallback (brak retry) |
| Czujnik wyciągnięty (100cm) | 40cm | 100cm | +60cm | fallback (brak retry) |
| Prawdziwe opróżnienie | 40cm | 150cm | +110cm | retry → akceptuj |
| Szum czujnika | 40cm | 43cm | +3cm | akceptuj |

---

### 2026-03-07 - v0.3 (MAD Filtr)
**Całkowita przebudowa logiki filtrowania:**

**Zmiany w config.h:**
- MIN_VALID_DISTANCE: 23 → 25 cm
- MEASUREMENTS_PER_SERIES: 20 → 10
- USUNIĘTO: EXTREME_VALUES_TO_DISCARD
- NOWE: MAD_THRESHOLD_MULTIPLIER, MAD_CONSTANT, MAD_MIN_VALID_RATIO
- NOWE: FILL_THRESHOLD_SMALL (5cm), FILL_THRESHOLD_LARGE (15cm), FILL_MAX_RETRIES (3)
- NOWE: FIRST_CYCLE_FALLBACK_CM (100cm)

**Zmiany w measurement.h:**
- Rozszerzony struct MeasurementResult o nowe pola:
  - suspiciousFillDetected, suspiciousFillRetries, suspiciousFillDelta, isFallback
- Nowy konstruktor z parametrem lastAcceptedValue

**Nowa logika filtrowania (5 poziomów):**
1. Filtr zakresu (25-170 cm) - bez zmian
2. MAD filtr - mediana → MAD → odrzuć outliery > 3×1.4826×MAD → fallback jeśli <50% zostało
3. Directional validation - opróżnienie=akceptuj, napełnienie<5cm=akceptuj, >15cm=Poziom4
4. Suspicious fill - powtórz serię max 3×, fallback do ostatniego accepted
5. Mediana z median - bez zmian

**Symulacje potwierdzone:**
- Dataset 1: 10/10 serii zaakceptowane, wynik 100.42cm
- Dataset 2: 10/10 serii zaakceptowane, wynik 100.68cm (brudne dane)
- Dataset 3: 3/10 serii accepted, fallback użyty, suspiciousFillDetected=true
- Dataset 4: 10/10 serii accepted, duże opróżnienie zaakceptowane (50cm)

### 2026-03-04 - v1.1 (working, short bursts)
- Zmiana na 10 serii × 10 pomiarów
- Cross-Series Validation (max różnica 5cm, max 3 powtórzenia)
- Deep sleep zwiększony do 10 minut
- Odstęp między pomiarami: 1 sekunda
- Odstęp między seriami: 12 sekund
- Filtrowanie zakresu: 23-160 cm
- Logika: mediana serii (po odrzuceniu 2 min/2 max) → mediana z median

### 2026-02-22 - Poprawki komunikacji ESP-NOW
- Dodano `#include <esp_wifi.h>` do espnow_manager.cpp
- Dodano `esp_wifi_set_channel()` w begin() - wymuszenie kanału WiFi
- Zwiększono `MAX_TIMEOUT_US` z 30000 na 38000 (timeout czujnika)
- Poprawiono `addPeer()` - kopiowanie MAC przed memset
- Poprawiono `onDataReceived()` - wykrywanie odbiornika przez ACK z packetId=0
- Poprawiono `sendData()` - pętla czeka też w stanie SENDING
- Dodano sprawdzanie `esp_now_is_peer_exist()` przed dodawaniem peera
