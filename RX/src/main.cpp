#include <Arduino.h>
#include <esp_timer.h>
#include "config.h"
#include "display.h"
#include "espnow_receiver.h"
#include "storage.h"
#include "history_sync.h"
#include "txlog.h"

DisplayManager display;
EspNowReceiver espNowReceiver;
Storage storage;
HistorySync historySync;

// Czas 64-bitowy [ms] od startu (esp_timer) - nie zawija sie po 49,7 dnia jak millis() (uint32).
// Wartosci "chwila zdarzenia" sa int64_t: po przywroceniu z pamieci moga wypasc przed momentem startu (wartosc ujemna).
static inline int64_t nowMs() {
    return (int64_t)(esp_timer_get_time() / 1000);
}

int64_t lastMeasurementMillis = 0;   // ostatni pakiet (dowolny) - ekran, ostrzeżenie 25h
int64_t lastTimeUpdateMillis = 0;
bool hasReceivedData = false;
bool warningShown = false;

// Ostatni POPRAWNY pomiar - dioda statusu i zapis w pamięci
int64_t lastValidMillis = 0;
float lastValidRaw = 0;
bool hasValidMeasurement = false;
int64_t lastSnapshotMillis = 0;

// Wiek [s] zapisywany w pamięci trwałej (uint32, nasycony)
static uint32_t ageSecondsOf(int64_t ageMs) {
    if (ageMs < 0) return 0;
    int64_t s = ageMs / 1000;
    return s > 100000000LL ? 100000000UL : (uint32_t)s;
}

// Wspólna obsługa pomiaru (pakiet ESP-NOW lub komenda testowa)
// pts/n = historia z pakietu TX (opcjonalnie)
static void handleMeasurement(float rawDistance, int64_t currentMillis, const HistPointIn* pts = nullptr, uint8_t n = 0) {
    bool valid = display.showMeasurement(rawDistance, pts, n);

    lastMeasurementMillis = currentMillis;
    lastTimeUpdateMillis = currentMillis;
    hasReceivedData = true;
    warningShown = false;

    if (valid) {
        lastValidMillis = currentMillis;
        lastValidRaw = rawDistance;
        hasValidMeasurement = true;
        lastSnapshotMillis = currentMillis;
        storage.saveSnapshot(lastValidRaw, 0);
        if (pts && n > 0) {
            storage.saveHistory(historySync.blob());   // po utracie zasilania RX prognoza wraca od razu
        }
    }
}

// Błąd krytyczny przy starcie: pokaż komunikat i zrestartuj urządzenie (samoleczenie zamiast wiszenia na ścianie)
static void failAndRestart(const char* message) {
    display.showError(message);
    delay(10000);
    ESP.restart();
}

void setup() {
    Serial.begin(SERIAL_BAUD_RATE);

    DEBUG_PRINT("========================================");
    DEBUG_PRINTF("  ESP32 RX v%s - ODBIORNIK (ILI9341)\n", FW_VERSION);
    DEBUG_PRINT("========================================");

    DEBUG_PRINT("[INIT] Inicjalizacja wyswietlacza...");
    if (!display.begin()) {
        DEBUG_PRINT("[INIT] BLAD: Nie mozna zainicjalizowac wyswietlacza!");
        delay(10000);
        ESP.restart();
    }
    DEBUG_PRINT("[INIT] Wyswietlacz gotowy");

    DEBUG_PRINT("[INIT] Inicjalizacja ESP-NOW...");
    if (!espNowReceiver.begin()) {
        DEBUG_PRINT("[INIT] BLAD: Nie mozna zainicjalizowac ESP-NOW! Restart za 10 s");
        failAndRestart("ESP-NOW init failed");
    }

    espNowReceiver.printMAC();
    DEBUG_PRINT("[INIT] ESP-NOW gotowy");

    txLog.begin();  // logi nadajnika (LittleFS) + komendy Serial TXLOG

    historySync.begin(storage);   // odciecie po RESET + ostatnia historia z NVS

    // Przywrócenie ostatniego poprawnego pomiaru po utracie zasilania
    float savedRaw;
    uint32_t savedAgeSec;
    if (storage.load(savedRaw, savedAgeSec)) {
        int64_t now = nowMs();
        lastValidRaw = savedRaw;
        lastValidMillis = now - (int64_t)savedAgeSec * 1000LL;
        lastMeasurementMillis = lastValidMillis;
        lastTimeUpdateMillis = now;
        lastSnapshotMillis = now;
        hasValidMeasurement = true;
        hasReceivedData = true;
        HistPointIn restored[MEAS_HIST_MAX];
        const uint8_t restoredN = historySync.restorePoints(restored);
        if (restoredN > 0) {
            display.restoreHistory(restored, restoredN, savedAgeSec);   // prognoza od razu po restarcie
        }
        display.showRestored(savedRaw, savedAgeSec);
        DEBUG_PRINTF("[INIT] Przywrocono ostatni pomiar: %.1f cm, wiek %lu s\n", savedRaw, (unsigned long)savedAgeSec);
    } else {
        display.showWaiting();
    }

    DEBUG_PRINT("[MAIN] Odbiornik gotowy! Nasluchuje danych...");
}

void loop() {
    int64_t currentMillis = nowMs();

    espNowReceiver.poll();            // pakiety z kolejki -> przetworzenie + ACK (zanim ruszy rysowanie ekranu)
    espNowReceiver.sendPendingResponse();
    txLog.loop(espNowReceiver);

    if (espNowReceiver.hasNewData()) {
        ReceivedData data = espNowReceiver.getData();

        DEBUG_PRINT("========================================");
        DEBUG_PRINT("[MAIN] Nowy pomiar odebrany!");
        DEBUG_PRINTF("[MAIN] Odleglosc: %.2f cm\n", data.distanceCm);
        DEBUG_PRINTF("[MAIN] Pomiarow: %d\n", data.validReadings);
        DEBUG_PRINTF("[MAIN] Pakiet ID: %d\n", data.packetId);
        DEBUG_PRINT("========================================");

        if (data.hasHistory) {
            HistPointIn pts[MEAS_HIST_MAX];
            uint8_t n = 0;
            if (historySync.process(data, pts, n)) {
                handleMeasurement(pts[0].rawCm, currentMillis, pts, n);
            } else {
                DEBUG_PRINT("[MAIN] Pakiet pominiety (sprzed RESET albo nieaktualny)");
            }
        } else {
            handleMeasurement(data.distanceCm, currentMillis);
        }

        espNowReceiver.clearNewDataFlag();
    }

    if (hasReceivedData && !warningShown) {
        if (currentMillis - lastTimeUpdateMillis >= 5000) {
            uint32_t secondsSinceLastPacket = ageSecondsOf(currentMillis - lastMeasurementMillis);
            display.updateTimeSinceLastPacket(secondsSinceLastPacket);
            lastTimeUpdateMillis = currentMillis;
        }
    }

    if (hasReceivedData && !warningShown && (currentMillis - lastMeasurementMillis >= NO_DATA_TIMEOUT)) {
        uint32_t sec = ageSecondsOf(currentMillis - lastMeasurementMillis);
        display.showNoDataWarning(sec);
        warningShown = true;
    }

    // Dioda statusu (wiek ostatniego poprawnego pomiaru)
    if (hasValidMeasurement) {
        display.updateStatusLed(currentMillis - lastValidMillis);

        // Okresowy zapis wieku - po utracie zasilania wiek liczy się dalej od tej wartości
        if (currentMillis - lastSnapshotMillis >= SNAPSHOT_INTERVAL_MS) {
            storage.saveSnapshot(lastValidRaw, ageSecondsOf(currentMillis - lastValidMillis));
            lastSnapshotMillis = currentMillis;
        }
    }

    // Przycisk RESET (przytrzymanie 3 s) - używany po każdym wywozie.
    // Po RESET odbiornik wraca do stanu początkowego: pierwszy odebrany pakiet jest "nowym startem"
    // (czysta historia, brak porównań ze starymi danymi).
    if (display.pollResetButton()) {
        DEBUG_PRINT("[MAIN] RESET przytrzymany - kasuje dane");
        storage.clear();
        historySync.onManualReset(storage);   // odciecie: pakiety TX sprzed RESET (stara historia) beda ignorowane
        display.performReset();
        hasReceivedData = false;
        warningShown = false;
        hasValidMeasurement = false;
        espNowReceiver.clearNewDataFlag();
    }

    delay(10);
}
