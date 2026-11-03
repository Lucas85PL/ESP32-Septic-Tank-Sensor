#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

#define FW_VERSION "2.2.0"

// ==================== PINY WYSWIETLACZA ILI9341 (E32R28T) ====================
// Wyswietlacz: HSPI (wlasne piny); dotyk XPT2046: osobna magistrala (VSPI, globalny SPI)
#define DISPLAY_MOSI 13
#define DISPLAY_MISO 12
#define DISPLAY_SCLK 14
#define DISPLAY_CS   15
#define DISPLAY_DC   2
#define DISPLAY_RST  -1    // reset wyswietlacza podpiety do EN plytki
#define DISPLAY_BL   21    // Backlight (HIGH = wlaczone) - zweryfikowane na plytce
#define DISPLAY_SPI_HZ 20000000   // zegar SPI wyswietlacza

// ==================== DOTYK XPT2046 ====================
#define TOUCH_SCLK 25
#define TOUCH_MISO 39
#define TOUCH_MOSI 32
#define TOUCH_CS   33
#define TOUCH_IRQ  36   // nieuzywany (odczyt przez polling)
#define TOUCH_Z_MIN 300  // min. nacisk uznawany za dotyk (rysik; palec wymaga ok. 100)
// Kalibracja (surowe wartosci XPT2046 -> piksele, przy ts.setRotation(1)).
// Jesli przycisk reaguje obok - popraw wartosci (debug wypisuje wspolrzedne dotyku).
#define TOUCH_X_MIN 200
#define TOUCH_X_MAX 3700
#define TOUCH_Y_MIN 240
#define TOUCH_Y_MAX 3800

// ==================== WYŚWIETLACZ ====================
#define DISPLAY_WIDTH  320
#define DISPLAY_HEIGHT 240
#define DISPLAY_ROTATION 3   // 3 = obudowa v2.0 (USB z LEWEJ patrzac na ekran); 1 = obrot o 180 st. (USB z prawej, obudowa v1.0)
                             // Dotyk jest odwracany automatycznie (display.cpp, readTouch -> pollResetButton)

// ==================== PRZYCISK RESET ====================
#define RESET_BTN_X 200
#define RESET_BTN_Y 198
#define RESET_BTN_W 110
#define RESET_BTN_H 36
#define RESET_HOLD_MS 3000   // czas przytrzymania

// ==================== DIODA STATUSU (wiek ostatniego poprawnego pomiaru) ====================
#define STATUS_ORANGE_AFTER_MS 90000000LL    // 25h - od tego momentu pomaranczowa
#define STATUS_RED_AFTER_MS    180000000LL   // 50h - od tego momentu czerwona migajaca
#define STATUS_BLINK_MS 500
#define SNAPSHOT_INTERVAL_MS 3600000LL       // co ile zapisywac wiek pomiaru do pamieci (1h)

// ==================== ESP-NOW ====================
#define ESPNOW_CHANNEL 1

// ==================== ZAKRES POMIARU ====================
// USTAW WG SWOJEGO ZBIORNIKA I MONTAZU CZUJNIKA (odleglosci w cm, mierzone od czujnika):
#define SENSOR_HEIGHT_OFFSET 0   // Korekta montazowa [cm]: corrected = raw - offset. 0 = bez korekty (surowy odczyt czujnika)
#define MIN_DISTANCE 25      // Pelny zbiornik = 100% (po korekcie). 25 cm = granica strefy martwej czujnika JSN-SR04T
#define MAX_DISTANCE 155     // Pusty zbiornik = 0% (po korekcie). Przyklad: 155 cm - zmierz odleglosc od czujnika do dna/pustego poziomu
#define HISTORY_SIZE 14      // Pomiarów w historii do średniej
#define EMPTY_THRESHOLD 50   // Próg cm do wykrycia opróżnienia
#define FORECAST_MIN_POINTS 7      // min. pomiarów (rzeczywistych) w historii dla prognozy z regresji (z HISTORY_SIZE ostatnich) ...
#define FORECAST_MIN_SPAN_H 35.0   // ... rozpietych na co najmniej tyle godzin (7 pomiarow co 6 h = 36 h)
#define FORECAST_PRIOR_CM_PER_DAY 6.0  // do czasu uzbierania danych (kolor pomaranczowy): zalozone tempo napelniania [cm/dobe]
#define FORECAST_DEDUP_MS 600000UL // pakiety bliżej niż 10 min (powtórki po utraconym ACK) liczą się jako jeden punkt historii
#define NO_DATA_TIMEOUT 90000000LL // 25h w ms - brak danych = ostrzeżenie (czas w RX jest 64-bitowy: esp_timer, bez zawijania po 49,7 dnia)

// ==================== LOGI NADAJNIKA (TX -> RX) ====================
#define TXLOG_FILE_CUR        "/txlog.txt"
#define TXLOG_FILE_OLD        "/txlog.old"
#define TXLOG_MAX_FILE_BYTES  400000   // po przekroczeniu: txlog.txt -> txlog.old (stary .old kasowany)
#define TXLOG_MAX_RECORD      10240    // max rozmiar jednego rekordu (cykl TX) skladanego w RAM

// ==================== SERIAL DEBUG ====================
#define SERIAL_BAUD_RATE 115200
#define DEBUG_ENABLED true

// Podczas zrzutu logu TX na Serial (komenda TXLOG DUMP) komunikaty diagnostyczne sa wyciszone,
// zeby nie mieszaly sie z danymi.
extern volatile bool g_serialQuiet;

#if DEBUG_ENABLED
    #define DEBUG_PRINT(x) do { if (!g_serialQuiet) Serial.println(x); } while (0)
    #define DEBUG_PRINTF(fmt, ...) do { if (!g_serialQuiet) Serial.printf(fmt, ##__VA_ARGS__); } while (0)
#else
    #define DEBUG_PRINT(x)
    #define DEBUG_PRINTF(fmt, ...)
#endif

#endif
