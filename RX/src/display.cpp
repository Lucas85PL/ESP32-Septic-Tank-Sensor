#include "display.h"
#include <esp_sleep.h>

#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSansBold18pt7b.h>
#include <Fonts/FreeSansBold24pt7b.h>

// Motyw "Pierscien": granat + wskaznik kolowy. ILI9341 = standardowy RGB565
#define RGB565(r, g, b) ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))
#define COL_BG     RGB565(11, 18, 32)
#define COL_TRACK  RGB565(30, 42, 68)
#define COL_TXT    RGB565(236, 241, 250)
#define COL_DIM    RGB565(125, 140, 168)
#define COL_GREEN  RGB565(46, 204, 143)
#define COL_AMBER  RGB565(245, 185, 66)
#define COL_RED    RGB565(255, 90, 95)
#define COL_ORANGE RGB565(255, 150, 40)
#define COL_OFF    RGB565(70, 70, 70)
#define COL_ACCENT RGB565(92, 140, 255)

#define LED_X 297
#define LED_Y 20

// Pierscien na ekranie pomiaru
#define GAUGE_CX 92
#define GAUGE_CY 122
#define GAUGE_R  68
#define GAUGE_TH 13
// Kolumna danych po prawej
#define COL_X 185
#define COL_W 135

#define RTC_MAGIC 0x44515441

RTC_DATA_ATTR RtcData rtcData;

DisplayManager::DisplayManager()
    : _dispSpi(HSPI)
    , _tft(&_dispSpi, DISPLAY_DC, DISPLAY_CS, DISPLAY_RST)
    , _lastDistance(-1.0f)
    , _initialized(false)
    , _historyIndex(0)
    , _historyCount(0)
    , _lastDistanceForEmptyCheck(-1.0f)
    , _blinkState(false)
    , _lastBlinkMillis(0)
    , _errorCount(0)
    , _sensorError(false)
    , _ledColor(0xFFFFFFFF)
    , _buttonVisible(false)
    , _holdStartMillis(0)
    , _lastPressMillis(0)
    , _lastButtonDrawMillis(0)
    , _touchWasDown(false) {
    memset(_history, 0, sizeof(_history));
}

bool DisplayManager::begin() {
    DEBUG_PRINT("[DISPLAY] Inicjalizacja...");

    pinMode(DISPLAY_BL, OUTPUT);
    digitalWrite(DISPLAY_BL, HIGH);

    _dispSpi.begin(DISPLAY_SCLK, DISPLAY_MISO, DISPLAY_MOSI, DISPLAY_CS);
    // Dotyk: globalny SPI na osobnych pinach; jego wewnętrzne SPI.begin() jest potem ignorowane
    SPI.begin(TOUCH_SCLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
    
    _tft.begin(DISPLAY_SPI_HZ);

    // Diagnostyka: odczyt z kontrolera przez MISO. Poprawnie: ID4=0x009341, RDMODE=0x9C
    DEBUG_PRINTF("[DISPLAY] ILI9341 ID4=0x%02X%02X%02X, RDMODE=0x%02X (oczekiwane 0x009341 / 0x9C)\n",
                 _tft.readcommand8(0xD3, 1), _tft.readcommand8(0xD3, 2), _tft.readcommand8(0xD3, 3),
                 _tft.readcommand8(ILI9341_RDMODE));

    _tft.setRotation(DISPLAY_ROTATION);
    _tft.fillScreen(COL_BG);

    pinMode(TOUCH_CS, OUTPUT);
    digitalWrite(TOUCH_CS, HIGH);

    _initialized = true;

    resetHistory();

    DEBUG_PRINT("[DISPLAY] Zainicjalizowany pomyslnie");

    showWaiting();

    return true;
}

void DisplayManager::clear() {
    if (!_initialized) return;
    _tft.fillScreen(COL_BG);
}

// ==================== POMOCNICZE RYSOWANIE ====================

static uint16_t blend565(uint16_t c, uint16_t bg, uint8_t a) {
    int r = (c >> 11) & 31, g = (c >> 5) & 63, b = c & 31;
    int r2 = (bg >> 11) & 31, g2 = (bg >> 5) & 63, b2 = bg & 31;
    r = r2 + (r - r2) * a / 255;
    g = g2 + (g - g2) * a / 255;
    b = b2 + (b - b2) * a / 255;
    return (uint16_t)((r << 11) | (g << 5) | b);
}

// Luk grubosci 'thick'; katy w stopniach, zgodnie z ruchem wskazowek od godz. 3
static void drawArc(Adafruit_GFX& g, int cx, int cy, int r, float a0, float a1, int thick, uint16_t col) {
    int rad = thick / 2;
    for (float a = a0; a < a1; a += 2.0f) {
        float t = a * 0.0174533f;
        g.fillCircle(cx + (int)roundf(r * cosf(t)), cy + (int)roundf(r * sinf(t)), rad, col);
    }
    float t = a1 * 0.0174533f;
    g.fillCircle(cx + (int)roundf(r * cosf(t)), cy + (int)roundf(r * sinf(t)), rad, col);
}

// Tekst z czcionki GFX wycentrowany w poziomie; baseline = linia bazowa. Gdy za szeroki - mniejsza czcionka
static void textCentered(Adafruit_GFX& g, const char* s, int cx, int baseline, const GFXfont* big,
                         const GFXfont* small, int maxW, uint16_t col) {
    int16_t x1, y1; uint16_t w, h;
    g.setTextWrap(false);  // getTextBounds uwzglednia zawijanie - bez tego za dlugi tekst wyglada na "mieszczacy sie"
    g.setFont(big);
    g.getTextBounds(s, 0, 0, &x1, &y1, &w, &h);
    if (small && w > maxW) {
        g.setFont(small);
        g.getTextBounds(s, 0, 0, &x1, &y1, &w, &h);
    }
    g.setTextColor(col);
    g.setCursor(cx - (int)w / 2 - x1, baseline);
    g.print(s);
}

// Tekst wycentrowany w poziomie i pionie wokol (cx, cy)
static void textCenteredXY(Adafruit_GFX& g, const char* s, int cx, int cy, const GFXfont* f, uint16_t col) {
    int16_t x1, y1; uint16_t w, h;
    g.setTextWrap(false);
    g.setFont(f);
    g.getTextBounds(s, 0, 0, &x1, &y1, &w, &h);
    g.setTextColor(col);
    g.setCursor(cx - (int)w / 2 - x1, cy - (y1 + (int)h / 2));
    g.print(s);
}

// Wartosc od lewej (x), czcionka 'big' lub 'small' gdy nie miesci sie w maxW
static void drawValue(Adafruit_GFX& g, const char* s, int x, int baseline, int maxW,
                      const GFXfont* big, const GFXfont* small, uint16_t col) {
    int16_t x1, y1; uint16_t w, h;
    g.setTextWrap(false);  // bez zawijania: pomiar szerokosci prawdziwy, a litery nie "uciekaja" do nastepnego wiersza
    g.setFont(big);
    g.getTextBounds(s, x, baseline, &x1, &y1, &w, &h);
    if (small && (x1 - x) + (int)w > maxW) g.setFont(small);
    g.setTextColor(col);
    g.setCursor(x, baseline);
    g.print(s);
}

// Maly podpis wersalikami z rozstrzeleniem liter (czcionka wbudowana 6x8)
static void drawLabel(Adafruit_GFX& g, const char* s, int x, int y, uint16_t col, int spacing, bool centered) {
    g.setFont(nullptr);
    g.setTextSize(1);
    g.setTextColor(col);
    int len = strlen(s);
    int width = len * (6 + spacing) - spacing;
    if (centered) x -= width / 2;
    for (int i = 0; i < len; i++) {
        g.setCursor(x, y);
        g.print(s[i]);
        x += 6 + spacing;
    }
}

void DisplayManager::showWaiting() {
    if (!_initialized) return;

    _tft.fillScreen(COL_BG);
    _buttonVisible = false;
    _holdStartMillis = 0;
    _ledColor = 0xFFFFFFFF;

    drawArc(_tft, 160, 100, 52, 135, 405, 8, COL_TRACK);
    drawArc(_tft, 160, 100, 52, 200, 250, 8, COL_ACCENT);
    textCenteredXY(_tft, "...", 160, 100, &FreeSansBold18pt7b, COL_DIM);

    textCentered(_tft, "Oczekiwanie na dane", 160, 186, &FreeSansBold12pt7b, &FreeSansBold9pt7b, 300, COL_TXT);

    char buf[16];
    snprintf(buf, sizeof(buf), "KANAL %d", ESPNOW_CHANNEL);
    drawLabel(_tft, buf, 160, 198, COL_DIM, 2, true);
}

bool DisplayManager::showMeasurement(float distanceCm, const HistPointIn* pts, uint8_t n) {
    if (!_initialized) return false;

    // Korekta offsetu: czujnik zamontowany SENSOR_HEIGHT_OFFSET cm ponad zbiornikiem
    float correctedDistance = distanceCm - SENSOR_HEIGHT_OFFSET;

    // Walidacja raw odczytu (przed korektą)
    bool validMeasurement = (distanceCm >= 0 && distanceCm <= (MAX_DISTANCE + SENSOR_HEIGHT_OFFSET) + 25);

    if (validMeasurement) {
        _errorCount = 0;
        _sensorError = false;
        _lastDistance = correctedDistance;
        _blinkState = true;
        _lastBlinkMillis = millis();
        if (pts && n > 0) {
            setHistory(pts, n, 0);   // historia z pakietu TX (zatwierdzone pomiary z wiekiem)
        } else {
            addToHistory(correctedDistance, millis());
        }
    } else {
        _errorCount++;
        if (_errorCount >= 6) {
            _sensorError = true;
            DEBUG_PRINT("[DISPLAY] BLAD: Wykryto problem z czujnikiem");
        }
        DEBUG_PRINTF("[DISPLAY] Odrzucono pomiar: %.1f cm raw (poza zakresem)\n", distanceCm);
    }

    redraw(validMeasurement, correctedDistance, 0);

    if (validMeasurement) {
        float percent = (MAX_DISTANCE - _lastDistance) / (MAX_DISTANCE - MIN_DISTANCE) * 100.0f;
        if (percent < 0) percent = 0;
        if (percent > 100) percent = 100;
        DEBUG_PRINTF("[DISPLAY] Wyswietlono: %.1f cm raw -> %.1f cm (%.0f%%)\n", distanceCm, correctedDistance, percent);
    }
    return validMeasurement;
}

void DisplayManager::showRestored(float rawDistanceCm, uint32_t ageSeconds) {
    if (!_initialized) return;

    // Tylko ostatnia wartość - historia i EWMA startują od zera (jak po resecie)
    float correctedDistance = rawDistanceCm - SENSOR_HEIGHT_OFFSET;
    _lastDistance = correctedDistance;
    _errorCount = 0;
    _sensorError = false;

    redraw(true, correctedDistance, ageSeconds);
    DEBUG_PRINTF("[DISPLAY] Przywrocono pomiar: %.1f cm raw, wiek %lu s\n", rawDistanceCm, (unsigned long)ageSeconds);
}

void DisplayManager::redraw(bool validMeasurement, float correctedDistance, uint32_t ageSeconds) {
    float percent;
    if (_sensorError || _lastDistance < 0) {
        percent = 0;
    } else {
        percent = (MAX_DISTANCE - _lastDistance) / (MAX_DISTANCE - MIN_DISTANCE) * 100.0f;
        if (percent < 0) percent = 0;
        if (percent > 100) percent = 100;
    }

    _tft.fillScreen(COL_BG);
    _ledColor = 0xFFFFFFFF;   // dioda zostanie przerysowana przez updateStatusLed()

    // --- pierscien z procentem ---
    drawArc(_tft, GAUGE_CX, GAUGE_CY, GAUGE_R, 135, 405, GAUGE_TH, COL_TRACK);
    if (percent > 0 && !_sensorError) {
        drawArc(_tft, GAUGE_CX, GAUGE_CY, GAUGE_R, 135, 135 + 270.0f * percent / 100.0f, GAUGE_TH, getBarColor(percent));
    }
    char buf[24];
    if (_sensorError) {
        snprintf(buf, sizeof(buf), "--");
    } else {
        snprintf(buf, sizeof(buf), "%d", (int)percent);
    }
    textCenteredXY(_tft, buf, GAUGE_CX, GAUGE_CY - 4, &FreeSansBold24pt7b, COL_TXT);
    drawLabel(_tft, "% ZAPELNIENIA", GAUGE_CX, 150, COL_DIM, 0, true);

    // --- kolumna danych ---
    drawLabel(_tft, "WOLNE MIEJSCE", COL_X, 36, COL_DIM, 1, false);
    if (validMeasurement && !_sensorError) {
        snprintf(buf, sizeof(buf), "%d cm", (int)correctedDistance);
    } else {
        snprintf(buf, sizeof(buf), "--- cm");
    }
    drawValue(_tft, buf, COL_X, 84, COL_W, &FreeSansBold18pt7b, &FreeSansBold12pt7b, COL_TXT);

    _tft.drawFastHLine(COL_X, 108, 115, COL_TRACK);

    drawLabel(_tft, "POMIAR", COL_X, 118, COL_DIM, 1, false);
    drawTimeValue(ageSeconds);

    drawLabel(_tft, "PELNY ZA", COL_X, 158, COL_DIM, 1, false);
    drawDaysValue();

    if (_sensorError) {
        _tft.setFont(&FreeSansBold9pt7b);
        _tft.setTextColor(COL_RED);
        _tft.setCursor(24, 220);
        _tft.print("BLAD CZUJNIKA");
    }

    drawResetButton(0);
    _buttonVisible = true;
}

uint16_t DisplayManager::getBarColor(float percent) {
    if (percent >= 80) {
        return COL_RED;
    } else if (percent >= 60) {
        return COL_AMBER;
    } else {
        return COL_GREEN;
    }
}

void DisplayManager::drawTimeValue(uint32_t seconds) {
    char buf[24];
    if (seconds == 0) {
        snprintf(buf, sizeof(buf), "teraz");
    } else if (seconds < 3600) {
        snprintf(buf, sizeof(buf), "%lu min temu", (unsigned long)(seconds / 60));
    } else {
        snprintf(buf, sizeof(buf), "%lu godz. temu", (unsigned long)(seconds / 3600));
    }
    drawValue(_tft, buf, COL_X, 147, COL_W, &FreeSans12pt7b, &FreeSans9pt7b, COL_TXT);
}

void DisplayManager::drawDaysValue() {
    char buf[20];
    int lo = 0, hi = 0;
    bool open = false, provisional = false;
    const bool haveForecast = forecastDays(lo, hi, open, provisional);
    if (!haveForecast) {
        snprintf(buf, sizeof(buf), "-- dni");
    } else if (provisional) {
        // orientacyjnie (zalozone tempo 6 cm/dobe, <36 h danych): "~N dni" na pomaranczowo
        if (lo > 99) snprintf(buf, sizeof(buf), ">99 dni");
        else snprintf(buf, sizeof(buf), "~%d dni", lo);
    } else if (lo > 99) {
        snprintf(buf, sizeof(buf), ">99 dni");
    } else if (open) {
        snprintf(buf, sizeof(buf), ">%d dni", lo);
    } else if (hi > 99) {
        snprintf(buf, sizeof(buf), "%d-99+ dni", lo);
    } else if (hi > lo) {
        snprintf(buf, sizeof(buf), "%d-%d dni", lo, hi);
    } else {
        snprintf(buf, sizeof(buf), "%d dni", lo);
    }
    const uint16_t daysColor = !haveForecast ? COL_TXT : (provisional ? COL_ORANGE : COL_GREEN);
    drawValue(_tft, buf, COL_X, 187, COL_W, &FreeSans12pt7b, &FreeSans9pt7b, daysColor);
}

void DisplayManager::addToHistory(float distanceCm, uint32_t timestamp) {
    // Wywoz: gwaltowny wzrost odleglosci o > EMPTY_THRESHOLD (nadajnik przyjmuje taki skok dopiero po potwierdzeniu
    // w 2 cyklach albo po fizycznym resecie) - stara historia napelniania jest bezuzyteczna, zaczynamy od nowa.
    if (_lastDistanceForEmptyCheck > 0 && distanceCm > _lastDistanceForEmptyCheck + EMPTY_THRESHOLD) {
        DEBUG_PRINT("[DISPLAY] Wykryto oproznienie zbiornika - reset historii");
        resetHistory();
    }
    _lastDistanceForEmptyCheck = distanceCm;

    // Powtorka pakietu (utracone ACK -> nadajnik wysyla ponownie w ciagu sekund): nadpisz ostatni punkt zamiast dodawac
    if (_historyCount > 0) {
        uint8_t last = (_historyIndex + HISTORY_SIZE - 1) % HISTORY_SIZE;
        if ((uint32_t)(timestamp - _history[last].receivedMillis) < FORECAST_DEDUP_MS) {
            _history[last].distanceCm = distanceCm;
            _history[last].receivedMillis = timestamp;
            _history[last].synthetic = false;
            return;
        }
    }

    _history[_historyIndex].distanceCm = distanceCm;
    _history[_historyIndex].receivedMillis = timestamp;
    _history[_historyIndex].synthetic = false;
    _historyIndex = (_historyIndex + 1) % HISTORY_SIZE;
    if (_historyCount < HISTORY_SIZE) {
        _historyCount++;
    }
}

// Historia z pakietu TX zastepuje cala historie w RX (pts[0] = najnowszy). Znaczniki czasu = teraz - wiek (uint32 millis, roznice modulo 2^32).
void DisplayManager::setHistory(const HistPointIn* pts, uint8_t n, uint32_t extraAgeSec) {
    resetHistory();
    if (n > HISTORY_SIZE) n = HISTORY_SIZE;
    const uint32_t now = millis();
    for (int i = (int)n - 1; i >= 0; i--) {          // od najstarszego
        _history[_historyIndex].distanceCm = pts[i].rawCm - SENSOR_HEIGHT_OFFSET;
        _history[_historyIndex].receivedMillis = now - (uint32_t)(((uint64_t)extraAgeSec + pts[i].ageSec) * 1000ULL);
        _history[_historyIndex].synthetic = pts[i].synthetic;
        _historyIndex = (_historyIndex + 1) % HISTORY_SIZE;
        _historyCount++;
    }
    if (n > 0) _lastDistanceForEmptyCheck = pts[0].rawCm - SENSOR_HEIGHT_OFFSET;
}

void DisplayManager::restoreHistory(const HistPointIn* pts, uint8_t n, uint32_t extraAgeSec) {
    setHistory(pts, n, extraAgeSec);
    DEBUG_PRINTF("[DISPLAY] Odtworzono historie: %u pkt\n", (unsigned)_historyCount);
}

// Prognoza "Pelny za":
//  - >= FORECAST_MIN_POINTS rzeczywistych pomiarow rozpietych na >= FORECAST_MIN_SPAN_H godzin: regresja liniowa
//    (metoda najmniejszych kwadratow) odleglosc(czas); zakres = nachylenie +- 1 blad standardowy (provisional = false),
//  - w przeciwnym razie (np. po wywozie, zanim uzbieraja sie dane): prior - zalozone tempo FORECAST_PRIOR_CM_PER_DAY
//    (provisional = true, ekran pokazuje "~N dni" na pomaranczowo).
// Sztuczne 25.0 cm ze strefy martwej nie wchodzi do regresji. Zwraca false, gdy brak historii albo zbiornik sie nie napelnia.
bool DisplayManager::forecastDays(int& lo, int& hi, bool& open, bool& provisional) {
    provisional = false;
    if (_historyCount == 0) return false;

    const uint8_t newest = (_historyIndex + HISTORY_SIZE - 1) % HISTORY_SIZE;
    const double distToFull = (double)_history[newest].distanceCm - MIN_DISTANCE;
    if (distToFull <= 0) {
        lo = hi = 0;
        open = false;
        return true;
    }

    // punkty rzeczywiste od najnowszego; os czasu w godzinach wzgledem najnowszego rzeczywistego (<= 0)
    double xs[HISTORY_SIZE], ys[HISTORY_SIZE];
    int n = 0;
    uint32_t refTs = 0;
    for (int i = 0; i < _historyCount; i++) {
        const uint8_t idx = (newest + HISTORY_SIZE - i) % HISTORY_SIZE;
        if (_history[idx].synthetic) continue;
        if (n == 0) refTs = _history[idx].receivedMillis;
        xs[n] = -(double)((uint32_t)(refTs - _history[idx].receivedMillis)) / 3600000.0;
        ys[n] = _history[idx].distanceCm;
        n++;
    }
    const double spanH = (n >= 2) ? -xs[n - 1] : 0.0;

    if (n >= FORECAST_MIN_POINTS && spanH >= FORECAST_MIN_SPAN_H) {
        double sx = 0, sy = 0;
        for (int i = 0; i < n; i++) {
            sx += xs[i];
            sy += ys[i];
        }
        const double mx = sx / n, my = sy / n;
        double sxx = 0, sxy = 0, syy = 0;
        for (int i = 0; i < n; i++) {
            sxx += (xs[i] - mx) * (xs[i] - mx);
            sxy += (xs[i] - mx) * (ys[i] - my);
            syy += (ys[i] - my) * (ys[i] - my);
        }
        if (sxx <= 1e-6) return false;

        const double rate = -sxy / sxx;                    // cm/h, > 0 = napelnianie
        if (rate < 0.01) return false;                     // < 0,24 cm/dobe = brak widocznego napelniania
        double ssr = syy - sxy * sxy / sxx;
        if (ssr < 0) ssr = 0;
        const double se = sqrt(ssr / (n - 2) / sxx);       // blad standardowy nachylenia

        const double daysFast = distToFull / (rate + se) / 24.0;   // szybsze napelnianie = wczesniej
        lo = (int)floor(daysFast);
        open = (rate - se) <= 0.005;
        if (open) {
            hi = lo;
        } else {
            hi = (int)ceil(distToFull / (rate - se) / 24.0);
            if (hi < lo) hi = lo;
        }
        return true;
    }

    lo = hi = (int)lround(distToFull / FORECAST_PRIOR_CM_PER_DAY);
    open = false;
    provisional = true;
    return true;
}

void DisplayManager::resetHistory() {
    _historyIndex = 0;
    _historyCount = 0;
    _lastDistanceForEmptyCheck = -1.0f;
    memset(_history, 0, sizeof(_history));
}

void DisplayManager::updateTimeSinceLastPacket(uint32_t seconds) {
    if (!_initialized) return;

    _tft.fillRect(COL_X, 126, COL_W, 28, COL_BG);

    drawTimeValue(seconds);
}

void DisplayManager::showNoDataWarning(uint32_t secondsSinceLastPacket) {
    if (!_initialized) return;

    _tft.fillScreen(COL_BG);
    _ledColor = 0xFFFFFFFF;

    // Wykrzyknik w kole
    _tft.drawCircle(160, 52, 24, COL_RED);
    _tft.drawCircle(160, 52, 23, COL_RED);
    textCenteredXY(_tft, "!", 160, 52, &FreeSansBold18pt7b, COL_RED);

    textCentered(_tft, "BRAK POMIARU", 160, 110, &FreeSansBold18pt7b, &FreeSansBold12pt7b, 300, COL_RED);

    drawLabel(_tft, "OSTATNI POMIAR", 160, 130, COL_DIM, 2, true);

    uint32_t hours = secondsSinceLastPacket / 3600;
    char buf[48];
    if (_lastDistance < 0) {
        snprintf(buf, sizeof(buf), "%luh temu / --- cm (---%%)", (unsigned long)hours);
    } else {
        float percent = (MAX_DISTANCE - _lastDistance) / (MAX_DISTANCE - MIN_DISTANCE) * 100.0f;
        if (percent < 0) percent = 0;
        if (percent > 100) percent = 100;
        snprintf(buf, sizeof(buf), "%luh temu / %d cm (%d%%)", (unsigned long)hours, (int)_lastDistance, (int)percent);
    }
    textCentered(_tft, buf, 160, 163, &FreeSans12pt7b, &FreeSans9pt7b, 300, COL_TXT);

    drawResetButton(0);
    _buttonVisible = true;

    DEBUG_PRINTF("[DISPLAY] Brak pomiarow przez %lu h\n", (unsigned long)hours);
}

void DisplayManager::showError(const char* message) {
    if (!_initialized) return;

    _tft.fillScreen(COL_BG);
    _buttonVisible = false;

    textCenteredXY(_tft, "BLAD", 160, 86, &FreeSansBold24pt7b, COL_RED);
    _tft.drawFastHLine(130, 112, 60, COL_TRACK);
    textCentered(_tft, message, 160, 140, &FreeSans12pt7b, &FreeSans9pt7b, 300, COL_TXT);

    DEBUG_PRINTF("[DISPLAY] Blad: %s\n", message);
}

// ==================== DIODA STATUSU ====================

void DisplayManager::updateStatusLed(int64_t ageMs) {
    if (!_initialized) return;

    uint16_t color;
    if (ageMs < STATUS_ORANGE_AFTER_MS) {
        color = COL_GREEN;
    } else if (ageMs < STATUS_RED_AFTER_MS) {
        color = COL_ORANGE;
    } else {
        color = ((millis() / STATUS_BLINK_MS) % 2 == 0) ? COL_RED : COL_OFF;
    }

    if (color == _ledColor) return;
    _ledColor = color;

    _tft.fillCircle(LED_X, LED_Y, 13, blend565(color, COL_BG, 64));   // poswiata
    _tft.fillCircle(LED_X, LED_Y, 8, color);
}

// ==================== PRZYCISK RESET ====================

void DisplayManager::drawResetButton(float progress) {
    if (progress < 0) progress = 0;
    if (progress > 1) progress = 1;

    const int16_t r = RESET_BTN_H / 2;
    // czyszczenie calego prostokata przycisku (takze naroza poza zaokragleniem - po puszczeniu nie zostaja slady)
    _tft.fillRect(RESET_BTN_X, RESET_BTN_Y, RESET_BTN_W, RESET_BTN_H, COL_BG);

    // wypelnienie postepu wycinane scanline po scanline do ksztaltu "pigulki" (wewnetrzna pigulka, promien r-2)
    const int16_t innerX = RESET_BTN_X + 2;
    const int16_t innerW = RESET_BTN_W - 4;
    const int16_t innerH = RESET_BTN_H - 4;
    const float ri = innerH / 2.0f;
    const int16_t fillW = (int16_t)(innerW * progress);
    if (fillW > 0) {
        const int16_t fillRight = innerX + fillW;   // pierwsza kolumna poza wypelnieniem
        for (int16_t row = 0; row < innerH; row++) {
            float dy = (row + 0.5f) - ri;
            float inset = ri - sqrtf(max(0.0f, ri * ri - dy * dy));
            int16_t x0 = innerX + (int16_t)ceilf(inset);
            int16_t x1 = min<int16_t>(fillRight, innerX + innerW - (int16_t)ceilf(inset));
            if (x1 > x0) {
                _tft.drawFastHLine(x0, RESET_BTN_Y + 2 + row, x1 - x0, COL_RED);
            }
        }
    }
    _tft.drawRoundRect(RESET_BTN_X, RESET_BTN_Y, RESET_BTN_W, RESET_BTN_H, r, COL_DIM);

    textCenteredXY(_tft, "RESET", RESET_BTN_X + RESET_BTN_W / 2, RESET_BTN_Y + RESET_BTN_H / 2,
                   &FreeSansBold9pt7b, progress > 0 ? COL_TXT : COL_DIM);
}

// Własny odczyt XPT2046 (biblioteka ma zaszyty próg nacisku 400 - za wysoki dla palca)
static int16_t besttwoavg(int16_t x, int16_t y, int16_t z) {
    int16_t da = abs(x - y), db = abs(x - z), dc = abs(z - y);
    if (da <= db && da <= dc) return (x + y) >> 1;
    if (db <= da && db <= dc) return (x + z) >> 1;
    return (y + z) >> 1;
}

// Zwraca true, gdy nacisk >= TOUCH_Z_MIN. Współrzędne w tej samej skali co biblioteka przy setRotation(1).
bool DisplayManager::readTouch(int16_t& rawX, int16_t& rawY, int16_t& rawZ) {
    int16_t data[6] = {0, 0, 0, 0, 0, 0};

    SPI.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE0));
    digitalWrite(TOUCH_CS, LOW);
    SPI.transfer(0xB1);                           // Z1
    int16_t z1 = SPI.transfer16(0xC1) >> 3;       // Z2
    int z = z1 + 4095;
    int16_t z2 = SPI.transfer16(0x91) >> 3;       // X
    z -= z2;
    bool pressed = (z >= TOUCH_Z_MIN);
    if (pressed) {
        SPI.transfer16(0x91);                     // pierwszy pomiar X zawsze zaszumiony
        data[0] = SPI.transfer16(0xD1) >> 3;      // Y
        data[1] = SPI.transfer16(0x91) >> 3;
        data[2] = SPI.transfer16(0xD1) >> 3;
        data[3] = SPI.transfer16(0x91) >> 3;
    }
    data[4] = SPI.transfer16(0xD0) >> 3;          // ostatni Y + power down
    data[5] = SPI.transfer16(0) >> 3;
    digitalWrite(TOUCH_CS, HIGH);
    SPI.endTransaction();

    if (!pressed) return false;
    rawX = besttwoavg(data[0], data[2], data[4]);
    rawY = besttwoavg(data[1], data[3], data[5]);
    rawZ = (z > 4095) ? 4095 : z;
    return true;
}

bool DisplayManager::pollResetButton() {
    if (!_initialized || !_buttonVisible) return false;

    uint32_t now = millis();
    bool inButton = false;

    int16_t rx, ry, rz;
    if (readTouch(rx, ry, rz)) {
#if DISPLAY_ROTATION == 3
        // obraz obrocony o 180 st. wzgledem kalibracji dla rotacji 1 -> odwrocone osie dotyku
        int16_t x = map(rx, TOUCH_X_MAX, TOUCH_X_MIN, 0, DISPLAY_WIDTH);
        int16_t y = map(ry, TOUCH_Y_MAX, TOUCH_Y_MIN, 0, DISPLAY_HEIGHT);
#else
        int16_t x = map(rx, TOUCH_X_MIN, TOUCH_X_MAX, 0, DISPLAY_WIDTH);
        int16_t y = map(ry, TOUCH_Y_MIN, TOUCH_Y_MAX, 0, DISPLAY_HEIGHT);
#endif

        if (!_touchWasDown) {
            DEBUG_PRINTF("[TOUCH] raw=(%d,%d) z=%d -> ekran=(%d,%d)\n", rx, ry, rz, x, y);
        }
        _touchWasDown = true;

        const int16_t pad = 10;   // tolerancja trafienia
        inButton = (x >= RESET_BTN_X - pad && x <= RESET_BTN_X + RESET_BTN_W + pad &&
                    y >= RESET_BTN_Y - pad && y <= RESET_BTN_Y + RESET_BTN_H + pad);
    } else {
        _touchWasDown = false;
    }

    if (inButton) {
        _lastPressMillis = now;
        if (_holdStartMillis == 0) {
            _holdStartMillis = now;
            _lastButtonDrawMillis = now;
        }
    } else if (_holdStartMillis != 0 && now - _lastPressMillis > 250) {
        // puszczony (krótki zanik odczytu rezystancyjnego jest tolerowany)
        _holdStartMillis = 0;
        drawResetButton(0);
        return false;
    }

    if (_holdStartMillis != 0) {
        uint32_t held = now - _holdStartMillis;
        if (held >= RESET_HOLD_MS) {
            _holdStartMillis = 0;
            return true;
        }
        if (now - _lastButtonDrawMillis >= 150) {
            drawResetButton((float)held / RESET_HOLD_MS);
            _lastButtonDrawMillis = now;
        }
    }
    return false;
}

void DisplayManager::performReset() {
    if (!_initialized) return;

    resetHistory();
    _lastDistance = -1.0f;
    _errorCount = 0;
    _sensorError = false;
    _blinkState = false;
    DEBUG_PRINT("[DISPLAY] RESET - powrot do stanu poczatkowego");
    showWaiting();
}

void DisplayManager::saveToRtc() {
    rtcData.historyIndex = _historyIndex;
    rtcData.historyCount = _historyCount;
    rtcData.lastDistance = _lastDistance;
    rtcData.magic = RTC_MAGIC;
    memcpy(rtcData.history, _history, sizeof(_history));
}

bool DisplayManager::loadFromRtc() {
    if (rtcData.magic != RTC_MAGIC) {
        return false;
    }

    _historyIndex = rtcData.historyIndex;
    _historyCount = rtcData.historyCount;
    _lastDistance = rtcData.lastDistance;
    memcpy(_history, rtcData.history, sizeof(_history));

    if (_historyIndex >= HISTORY_SIZE) _historyIndex = 0;
    if (_historyCount > HISTORY_SIZE) _historyCount = HISTORY_SIZE;

    return true;
}
