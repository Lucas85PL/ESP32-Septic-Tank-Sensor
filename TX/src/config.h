#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

#define FW_VERSION "2.2.0"

// ==================== PINY ====================
#define PIN_TRIG 5
#define PIN_ECHO 18
#define PIN_MOSFET 23

// ==================== POMIARY ====================
#define SERIES_COUNT 6
#define MEASUREMENTS_PER_SERIES 10
#define SERIES_INTERVAL_MS 20000
#define MEASUREMENT_INTERVAL_MS 1000
#define TOTAL_MEASUREMENTS (SERIES_COUNT * MEASUREMENTS_PER_SERIES)
#define LEGACY_VALID_READINGS_SCALE 10  // pole validReadings w pakiecie zawsze w skali 0-10 (zgodnosc z odbiornikiem)

// ==================== ZAKRES POMIAROW ====================
#define MIN_VALID_DISTANCE 25.0f   // strefa martwa czujnika JSN-SR04T
#define MAX_VALID_DISTANCE 170.0f  // dno zbiornika ~165 cm + margines

// ==================== KONSENSUS NA POZIOMIE PROBEK (klastry) ====================
// Wszystkie poprawne probki cyklu (6 serii x 10) trafiaja do jednej puli. Szukamy najgestszych
// okien o szerokosci 2 x POOL_HALF_WIDTH_CM. Zepsute serie i bledne probki rozpraszaja sie po zakresie,
// a prawdziwy poziom tworzy gesty klaster.
#define POOL_HALF_WIDTH_CM 1.5f        // polowa szerokosci okna klastra
#define POOL_MIN_SAMPLES 12            // min. probek w klastrze (z 60) - inaczej cykl niewiarygodny
#define POOL_DOMINANCE_RATIO 1.5f      // klaster musi miec >= 1.5x wiecej probek niz drugi (gdy brak oczekiwanego)
#define POOL_MAX_CLUSTERS 3
#define POOL_PRIOR_MIN_SAMPLES 6       // klaster ZGODNY z oczekiwanym zakresem: nizszy prog probek ...
#define POOL_PRIOR_MIN_SERIES 3        // ... ale tylko gdy ma wsparcie z >= 3 roznych serii
#define POOL_SERIES_MIN_SAMPLES 3      // seria "zgadza sie z klastrem", gdy ma >= 3 probki w oknie (do validReadings)

// ==================== WALIDACJA MIEDZY CYKLAMI (zalezna od czasu) ====================
#define FILL_MAX_CM_PER_DAY 15.0f      // max szybkosc napelniania (spadek odleglosci) cm/dobe
#define RISE_NOISE_CM 5.0f             // wzrost odleglosci <= 5 cm = szum
#define SLOW_FILL_MAX_CM_PER_DAY 8.0f  // wolniejsze okno napelniania dla wynikow tuz nad strefa martwa ...
#define SLOW_FILL_ZONE_CM 10.0f        // ... (wynik < MIN_VALID_DISTANCE + 10 cm)
#define EMPTY_ZONE_MIN 140.0f          // wzrost odleglosci > 5 cm akceptowany tylko gdy wynik >= 140 cm (wywoz)
#define RISE_CONFIRM_TOL_CM 10.0f      // wzrost odleglosci (wywoz) wymaga 2 kolejnych zgodnych cykli (+-10 cm); bez potwierdzenia
                                       // przyjmowany jest tylko po fizycznym resecie TX (odlaczenie zasilania / przycisk EN)
#define MAX_REJECTED_CYCLES 4          // po 4 odrzuconych cyklach z rzedu (24 h): akceptuj i zresetuj odniesienie
#define NEAR_MIN_MARGIN_CM 5.0f        // wynik poza oknem i < MIN_VALID_DISTANCE + 5 cm = podejrzane echo strefy martwej:
                                       // nigdy nie resetuje odniesienia (okno rosnie z czasem i samo go dogoni)

// ==================== STREFA MARTWA (< 25 cm) ====================
#define DEADZONE_MIN_RATIO_PCT 50      // >= 50% probek ponizej 25 cm (i brak konsensusu)
#define DEADZONE_LAST_MAX_CM 70.0f     // ... a poprzedni wynik <= 70 cm => poziom w strefie martwej
#define DEADZONE_REPORTED_SERIES 4     // validReadings przy strefie martwej (z SERIES_COUNT)
#define DEADZONE_PLAUSIBLE_MARGIN_CM 5.0f  // strefa martwa liczona tylko gdy odniesienie mogloby tam dojsc (okno napelniania)
#define DEADZONE_MIN_SPREAD_CM 1.5f    // probki < 25 cm musza miec rozrzut (odch. std.) - stabilne echo to nie strefa martwa
#define DEADZONE_CONFIRM_CYCLES 6      // stan musi utrzymac sie 6 cykli (36 h) - odroznia pelny zbiornik od wyjetego czujnika

// ==================== FALLBACK ====================
#define FIRST_CYCLE_FALLBACK_CM 100.0f

// ==================== CZUJNIK ====================
#define SOUND_SPEED_CM_PER_US 0.0343f
#define MAX_TIMEOUT_US 38000
#define INVALID_READING -1.0f

// ==================== ESP-NOW ====================
#define ESPNOW_CHANNEL 1
#define ESPNOW_MAX_RETRIES 3
#define ESPNOW_RETRY_DELAY_MS 1000
#define ESPNOW_RECEIVER_DISCOVERY_TIMEOUT_MS 10000
#define ESPNOW_ACK_TIMEOUT_MS 2000
// Harmonogram ponawiania wysylki po braku ACK (sekundy snu przed kolejna proba).
// Przy ponawianiu nadajnik wykonuje swiezy pomiar, jesli odbiornik odpowiada. Ponawianie konczy sie
// przed kolejnym regularnym cyklem (6 h).
#define SEND_RETRY_COUNT 7
static const uint32_t SEND_RETRY_SCHEDULE_S[SEND_RETRY_COUNT] = {1800, 1800, 1800, 3600, 3600, 7200, 7200};
#define SEND_RETRY_MARGIN_S 120
#define FAILED_CYCLES_NO_RETRY 1       // po tylu nieudanych regularnych cyklach z rzedu (brak ACK) ponowienia sa wylaczone -
                                       // TX budzi sie tylko na regularny cykl (oszczednosc baterii przy dluzszej awarii odbiornika)        // nie planuj ponowienia, jesli do regularnego cyklu zostaje mniej

// ==================== PERSYSTENCJA ODNIESIENIA (flash) ====================
#define REF_FILE_PATH "/ref.bin"
#define HIST_FILE_PATH "/hist.bin"         // historia zatwierdzonych pomiarow (do 14), wysylana do RX razem z pomiarem
#define HIST_ASSUMED_GAP_S 10800UL         // po resecie TX wiek najnowszego punktu jest nieznany - zakladamy pol okresu pomiarowego (3 h)
#define REF_RESTORE_EXTRA_SECONDS 86400UL  // po przywroceniu z flash (reset zasilania): okno napelniania poszerzone o 24 h (czas bez zasilania jest nieznany)

// ==================== POWER ====================
#define DEEP_SLEEP_SECONDS 21600  // 6 godzin
#define WATCHDOG_TIMEOUT_MS 600000UL  // 10 min: awaryjny bezpiecznik - jesli wybudzenie trwa dluzej, wylacz czujnik i idz spac
#define RTC_STATE_MAGIC 0x52544333UL  // wersja ukladu zmiennych RTC (zmien przy zmianie struktur - wymusza czysty start)

// ==================== EVENT LOGGER ====================
// Kazdy cykl = osobny plik /c<ID>.txt (skrot + pelny log sesji). Przechowujemy ostatnie LOG_KEEP_CYCLES cykli,
// starsze sa kasowane. ID jest trwale (flash, /meta.bin) i razem z epoch tworzy unikalny identyfikator rekordu.
#define LOG_PARTITION_LABEL     "spiffs"
#define LOG_META_PATH           "/meta.bin"
#define LOG_KEEP_CYCLES         28
#define LOG_SESSION_BUFFER_SIZE 8192
#define LOG_MIN_FREE_BYTES      24576  // przed zapisem: jesli wolne < tyle, kasuj najstarsze rekordy

// ==================== WYSYLKA LOGOW DO ODBIORNIKA ====================
#define LOG_SYNC_BUDGET_MS        20000  // max czas wysylki logow w jednym wybudzeniu
#define LOG_CHUNK_ACK_TIMEOUT_MS  300
#define LOG_CHUNK_RETRIES         3

// ==================== CZUJNIK - ZASILANIE ====================
#define SENSOR_WARMUP_MS 500   // czas na start czujnika po wlaczeniu MOSFET-a (pomiar przed Wi-Fi)

// ==================== SERIAL DEBUG ====================
#define SERIAL_BAUD_RATE 115200
#define DEBUG_ENABLED true

#if DEBUG_ENABLED
    #define DEBUG_PRINT(x) Serial.println(x)
    #define DEBUG_PRINTF(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)
#else
    #define DEBUG_PRINT(x)
    #define DEBUG_PRINTF(fmt, ...)
#endif

#endif
