#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <SPI.h>
#include <esp_sleep.h>
#include "config.h"

struct MeasurementRecord {
    float distanceCm;
    uint32_t receivedMillis;
    bool synthetic;   // sztuczne 25.0 cm ze strefy martwej TX - nie wchodzi do regresji
};

// Punkt historii odebrany w pakiecie TX (najnowszy pierwszy w tablicy)
struct HistPointIn {
    float rawCm;        // surowa odleglosc [cm]
    uint32_t ageSec;    // wiek wzgledem chwili odbioru pakietu [s]
    bool synthetic;
};

struct RtcData {
    MeasurementRecord history[HISTORY_SIZE];
    uint8_t historyIndex;
    uint8_t historyCount;
    float lastDistance;
    uint32_t magic;
};

class DisplayManager {
public:
    DisplayManager();

    bool begin();
    void showWaiting();
    // Zwraca true, jeśli pomiar był poprawny
    // pts/n (opcjonalnie): historia z pakietu TX - zastępuje historię w RX (prognoza liczona z niej); bez nich: stary tryb (dopisanie punktu)
    bool showMeasurement(float distanceCm, const HistPointIn* pts = nullptr, uint8_t n = 0);
    // Odtworzenie historii po restarcie (z NVS); extraAgeSec = wiek zapisu; wołać PRZED showRestored()
    void restoreHistory(const HistPointIn* pts, uint8_t n, uint32_t extraAgeSec);
    // Przywrócenie ostatniego pomiaru po restarcie
    void showRestored(float rawDistanceCm, uint32_t ageSeconds);
    void updateTimeSinceLastPacket(uint32_t seconds);
    void showNoDataWarning(uint32_t secondsSinceLastPacket);
    void showError(const char* message);
    void clear();
    float getLastDistance() const { return _lastDistance; }

    // Dioda statusu: wiek ostatniego poprawnego pomiaru [ms]; wołać często (miganie)
    void updateStatusLed(int64_t ageMs);
    // Obsługa przycisku RESET; zwraca true po przytrzymaniu RESET_HOLD_MS
    bool pollResetButton();
    // Powrót do stanu jak przy pierwszym uruchomieniu ("Oczekiwanie na dane")
    void performReset();

private:
    SPIClass _dispSpi;   // wyświetlacz: HSPI; dotyk używa globalnego SPI (VSPI). Musi być przed _tft
    Adafruit_ILI9341 _tft;
    float _lastDistance;
    bool _initialized;

    MeasurementRecord _history[HISTORY_SIZE];
    uint8_t _historyIndex;
    uint8_t _historyCount;
    float _lastDistanceForEmptyCheck;

    bool _blinkState;
    uint32_t _lastBlinkMillis;
    uint8_t _errorCount;
    bool _sensorError;

    // Dioda statusu i przycisk RESET
    uint32_t _ledColor;        // ostatnio narysowany kolor (0xFFFFFFFF = do przerysowania)
    bool     _buttonVisible;
    uint32_t _holdStartMillis; // 0 = brak przytrzymania
    uint32_t _lastPressMillis;
    uint32_t _lastButtonDrawMillis;
    bool     _touchWasDown;

    void redraw(bool validMeasurement, float correctedDistance, uint32_t ageSeconds);
    void drawTimeValue(uint32_t seconds);
    void drawDaysValue();
    void drawResetButton(float progress);
    bool readTouch(int16_t& rawX, int16_t& rawY, int16_t& rawZ);
    uint16_t getBarColor(float percent);

    void addToHistory(float distanceCm, uint32_t timestamp);
    // Prognoza "Pelny za": regresja liniowa z historii. lo..hi = zakres w dniach; open = gorna granica nieokreslona
    // provisional = prognoza orientacyjna (zalozone tempo, za malo danych): ekran pokazuje ja na pomaranczowo
    bool forecastDays(int& lo, int& hi, bool& open, bool& provisional);
    void setHistory(const HistPointIn* pts, uint8_t n, uint32_t extraAgeSec);
    void resetHistory();
    void saveToRtc();
    bool loadFromRtc();
};

#endif
