#include <Arduino.h>
#include "config.h"
#include "ultrasonic_sensor.h"
#include "measurement.h"
#include "espnow_manager.h"
#include "power_manager.h"
#include "event_logger.h"
#include "ref_store.h"
#include "meas_history.h"
#include "log_sync.h"
#include <esp_timer.h>
#include <esp_sleep.h>

UltrasonicSensor* sensor = nullptr;
EspNowManager* espNowManager = nullptr;

// Wypisz na Serial i zapisz w logu biezacego cyklu
#define LOGM(...) do { DEBUG_PRINTF(__VA_ARGS__); eventLogger.logf(__VA_ARGS__); } while (0)

// RTC_DATA_ATTR - wartosci przezywaja deep sleep, resetuja sie tylko przy cold boot / utracie zasilania.
// Odniesienie miedzy cyklami: aktualizowane przy akceptacji pomiaru, niezaleznie od ACK.
// Po cold boot jest odtwarzane z flash (RefStore), wiec reset nie powoduje zaufania pierwszemu pomiarowi.
RTC_DATA_ATTR RefState refState = { FIRST_CYCLE_FALLBACK_CM, false, 0, 0, 0 };

// Wynik czekajacy na ponowna wysylke (po braku ACK)
RTC_DATA_ATTR bool pendingSend = false;
RTC_DATA_ATTR float pendingValue = 0.0f;
RTC_DATA_ATTR uint8_t pendingSeries = 0;          // zgodne serie (0..SERIES_COUNT) - do validReadings
RTC_DATA_ATTR uint8_t pendingRetryIdx = 0;        // indeks kolejnego odstepu w SEND_RETRY_SCHEDULE_S
RTC_DATA_ATTR uint32_t secondsToRegular = 0;      // ile zostalo do kolejnego regularnego cyklu pomiarowego
RTC_DATA_ATTR uint32_t elapsedSincePrevWake = 0;  // sekundy od poprzedniego wybudzenia (praca + sen) - do wieku odniesienia
RTC_DATA_ATTR uint32_t rtcMagic = 0;              // != RTC_STATE_MAGIC => RTC zawiera smieci / stary uklad: czysty start
RTC_DATA_ATTR uint8_t failedRegular = 0;          // ile kolejnych regularnych cykli skonczylo sie brakiem ACK (po serii ponowien)
RTC_DATA_ATTR bool watchdogFired = false;         // poprzednie wybudzenie przerwal bezpiecznik czasowy

// Bezpiecznik czasowy: normalne wybudzenie trwa ~3-4 min. Gdyby cos sie zawiesilo (flash, Wi-Fi), po WATCHDOG_TIMEOUT_MS
// wylaczamy czujnik i usypiamy uklad na pelny okres - bateria nie zostanie "wyssana" przez zawieszony program.
static void watchdogExpired(void*) {
    digitalWrite(PIN_MOSFET, LOW);
    watchdogFired = true;
    pendingSend = false;
    pendingRetryIdx = 0;
    elapsedSincePrevWake = (uint32_t)(WATCHDOG_TIMEOUT_MS / 1000UL) + DEEP_SLEEP_SECONDS;
    esp_sleep_enable_timer_wakeup((uint64_t)DEEP_SLEEP_SECONDS * 1000000ULL);
    esp_deep_sleep_start();
}

static void armWatchdog() {
    esp_timer_create_args_t args;
    memset(&args, 0, sizeof(args));
    args.callback = watchdogExpired;
    args.name = "cycle_wd";
    esp_timer_handle_t handle = nullptr;
    if (esp_timer_create(&args, &handle) == ESP_OK) {
        esp_timer_start_once(handle, (uint64_t)WATCHDOG_TIMEOUT_MS * 1000ULL);
    }
}

void initializeSerial(const char* bootReason) {
    Serial.begin(SERIAL_BAUD_RATE);
    while (Serial.available()) {
        Serial.read();
    }
    delay(300);

    Serial.println("\n\n========================================");
    Serial.printf("  ESP32 TX v%s - TRANSMITTER\n", FW_VERSION);
    Serial.println("========================================");
    Serial.printf("Czas kompilacji: %s %s\n", __DATE__, __TIME__);
    Serial.printf("SDK Version: %s\n", ESP.getSdkVersion());
    Serial.printf("Start: %s\n", bootReason);
    Serial.printf("Odniesienie: %.2f cm (valid=%d)\n", refState.value, refState.valid ? 1 : 0);
    Serial.println("========================================\n");
    Serial.flush();
}

void initializeSensor() {
    DEBUG_PRINT("[INIT] Inicjalizacja czujnika ultrasonicznego...");
    digitalWrite(PIN_MOSFET, HIGH);  // zasilanie czujnika wlaczane dopiero tuz przed pomiarem
    if (!sensor) {
        sensor = new UltrasonicSensor(PIN_TRIG, PIN_ECHO);
    }
    sensor->begin();
    delay(SENSOR_WARMUP_MS);  // czas na start czujnika po wlaczeniu zasilania
    DEBUG_PRINT("[INIT] Czujnik gotowy");
}

void sensorPowerOff() {
    digitalWrite(PIN_MOSFET, LOW);  // czujnik niepotrzebny podczas wysylki / logow
}

// Inicjalizacja ESP-NOW + discovery. Mozna wolac wielokrotnie (po shutdown()).
bool initializeEspNow() {
    DEBUG_PRINT("[INIT] Inicjalizacja ESP-NOW...");
    if (!espNowManager) {
        espNowManager = new EspNowManager();
    }

    if (!espNowManager->begin()) {
        DEBUG_PRINT("[INIT] BLAD: Nie udalo sie zainicjalizowac ESP-NOW");
        return false;
    }

    espNowManager->discoverReceiver();  // nieudane discovery niekrytyczne — sendValue ponowi probe

    DEBUG_PRINT("[INIT] ESP-NOW gotowy");
    return true;
}

// Po cold boot (RTC puste) przywroc odniesienie z flash. Okno napelniania jest poszerzone,
// bo nie wiadomo, jak dlugo urzadzenie bylo wylaczone.
void restoreReferenceIfNeeded() {
    if (refState.valid) {
        return;
    }

    RefState restored = refState;
    if (RefStore::load(restored)) {
        restored.secondsSinceRef += REF_RESTORE_EXTRA_SECONDS;
        refState = restored;
        DEBUG_PRINTF("[REF] Przywrocono odniesienie z flash: %.2f cm (%.1f h od aktualizacji)\n",
                     refState.value, refState.secondsSinceRef / 3600.0f);
    } else {
        DEBUG_PRINT("[REF] Brak odniesienia we flash - bootstrap przy pierwszym wiarygodnym cyklu");
    }
}

bool performMeasurement(MeasurementResult& result, bool isRetry, bool acceptRiseNow) {
    DEBUG_PRINT("\n========== CYKL POMIAROWY ==========");

    // Stan odniesienia PRZED pomiarem - potrzebny do rozpoznania wywozu / resetu odniesienia (czyszczenie historii)
    const bool prevValid = refState.valid;
    const float prevValue = refState.value;
    const uint8_t prevRejected = refState.rejectedCycles;
    if (acceptRiseNow && !isRetry) {
        refState.deadzoneCycles = 0;   // fizyczny reset TX: licznik strefy martwej liczy od nowa (czujnik byl wyjmowany)
    }

    MeasurementManager measurementManager(*sensor, refState, &eventLogger, isRetry, acceptRiseNow);
    result = measurementManager.performFullMeasurementCycle();

    RefStore::save(refState);  // odniesienie (i jego wiek) przetrwa reset / utrate zasilania; pomija stan bez odniesienia

    if (!result.isValid) {
        DEBUG_PRINT("[MAIN] Brak wiarygodnego wyniku - nic nie wysylam");
        return false;
    }

    MeasHistory::onAccepted(result, prevValid, prevValue, prevRejected, isRetry);
    LOGM("[MAIN] Historia: %u pkt, seq %lu, epoka %08lX\n", (unsigned)MeasHistory::count(),
         (unsigned long)MeasHistory::seq(), (unsigned long)MeasHistory::epoch());
    return true;
}

// validReadings w skali 0-10 (jak dotad), niezaleznie od SERIES_COUNT
uint8_t scaledValidReadings(uint8_t acceptedSeries) {
    return (uint8_t)((acceptedSeries * LEGACY_VALID_READINGS_SCALE + SERIES_COUNT / 2) / SERIES_COUNT);
}

// Tylko wysylka (z rediscovery) - odniesienie jest juz zapisane przy akceptacji pomiaru
bool sendValue(float value, uint8_t validReadings) {
    DEBUG_PRINT("\n========== WYSYLKA DANYCH ==========");

    // Odbiornik nie odpowiedzial na discovery sprzed chwili: nie ponawiamy go tu (kosztuje ~20 s radia).
    // Kolejna szansa: ponowienie po 30 min (jesli dozwolone) albo nastepny regularny cykl.
    if (!espNowManager->isReceiverKnown()) {
        LOGM("[MAIN] Odbiornik nieznany - pomijam wysylke (%.2f cm)\n", value);
        return false;
    }

    // Pakiet z historia zatwierdzonych pomiarow (najnowszy = biezacy); RX odtwarza z niego os czasu i prognoze
    MeasurementPacketV2 packet;
    const size_t packetLen = MeasHistory::buildPacket(packet, validReadings, value);

    if (espNowManager->sendMeasurementWithRetry(packet, packetLen)) {
        LOGM("[MAIN] Wysylka OK: %.2f cm\n", value);
        return true;
    }

    DEBUG_PRINT("\n[MAIN] Odbiornik znany, ale brak ACK - ponawiam probe z rediscovery...");

    for (int attempt = 1; attempt <= 2; attempt++) {
        DEBUG_PRINTF("[MAIN] Proba rediscovery %d/2\n", attempt);

        if (espNowManager->discoverReceiver()) {
            if (espNowManager->sendMeasurementWithRetry(packet, packetLen)) {
                LOGM("[MAIN] Wysylka OK po rediscovery %d: %.2f cm\n", attempt, value);
                return true;
            }
        }

        delay(1000);
    }

    LOGM("[MAIN] BLAD wysylki: brak ACK (%.2f cm)\n", value);
    return false;
}

const char* measFailReason(CycleStatus status) {
    return status == CycleStatus::REJECTED_JUMP ? "JUMP_REJECTED" : "NO_VALID_SERIES";
}

void setup() {
    pinMode(PIN_MOSFET, OUTPUT);
    digitalWrite(PIN_MOSFET, LOW);   // czujnik wylaczony do chwili pomiaru (initializeSensor)
    armWatchdog();

    if (rtcMagic != RTC_STATE_MAGIC) {  // pierwszy start po wgraniu / smieci w RTC: czysty stan
        refState = { FIRST_CYCLE_FALLBACK_CM, false, 0, 0, 0, 0, 0.0f };
        pendingSend = false;
        pendingValue = 0.0f;
        pendingSeries = 0;
        pendingRetryIdx = 0;
        secondsToRegular = 0;
        elapsedSincePrevWake = 0;
        failedRegular = 0;
        watchdogFired = false;
        MeasHistory::resetRtc();
        rtcMagic = RTC_STATE_MAGIC;
    }

    Serial.begin(SERIAL_BAUD_RATE);
    const char* bootReason = PowerManager::getBootReasonString();
    const bool manualBoot = PowerManager::isManualBoot();  // zasilanie / przycisk EN (tylko do rozpoznania nieoczekiwanych restartow)

    initializeSerial(bootReason);

    if (!eventLogger.begin()) {
        DEBUG_PRINT("[LOG] Kontynuuje bez zapisu na flash");
    }

    // Czas od poprzedniego wybudzenia (sen + praca) - odniesienie "starzeje sie" w rzeczywistym czasie,
    // takze przy krotkich wybudzeniach na ponowienie wysylki.
    if (refState.valid) {
        refState.secondsSinceRef += elapsedSincePrevWake;
    }
    MeasHistory::advanceClock(elapsedSincePrevWake);
    MeasHistory::begin();   // po cold boot: historia pomiarow z flash (do wyslania do RX razem z pomiarem)
    elapsedSincePrevWake = 0;
    restoreReferenceIfNeeded();

    eventLogger.beginSession(bootReason, refState.value);
    PowerManager::printWakeupReason();
    LOGM("[MAIN] Start: %s, odniesienie %.2f cm (%.1f h od aktualizacji)\n",
         bootReason, refState.value, refState.secondsSinceRef / 3600.0f);
    if (!manualBoot && strcmp(bootReason, "TIMER") != 0) {
        LOGM("[MAIN] UWAGA: nieoczekiwany restart (%s)\n", bootReason);
    }
    if (watchdogFired) {
        LOGM("[MAIN] UWAGA: poprzednie wybudzenie przerwal bezpiecznik czasowy (%lu s)\n",
             (unsigned long)(WATCHDOG_TIMEOUT_MS / 1000UL));
        watchdogFired = false;
    }

    const bool retryWake = pendingSend;
    // Fizyczny reset TX (odlaczenie zasilania / przycisk EN): pierwszy cykl przyjmuje wywoz bez potwierdzenia
    const bool acceptRiseNow = manualBoot && !retryWake;

    MeasurementResult result = {};
    bool measOk = false;
    bool sendOk = false;
    bool espOk = false;
    const char* failReason = "UNKNOWN";

    if (retryWake) {
        // Ponowna wysylka. Najpierw sprawdz, czy odbiornik odpowiada; jesli tak, wylacz radio,
        // wykonaj swiezy pomiar zamiast wysylac starej wartosci i dopiero potem wysylaj.
        LOGM("[MAIN] Retry wysylki %d/%d (poprzednia wartosc: %.2f cm)\n",
             (int)pendingRetryIdx, SEND_RETRY_COUNT, pendingValue);

        espOk = initializeEspNow();
        if (espOk && espNowManager->isReceiverKnown()) {
            espNowManager->shutdown();  // pomiar bez Wi-Fi

            initializeSensor();  // czujnik wlaczany dopiero teraz (nie podczas discovery)
            MeasurementResult fresh = {};
            if (performMeasurement(fresh, true, false)) {
                pendingValue = fresh.value;
                pendingSeries = fresh.acceptedSeriesCount;
                LOGM("[MAIN] Swiezy pomiar zamiast starej wartosci: %.2f cm\n", pendingValue);
            }
            sensorPowerOff();
            espOk = initializeEspNow();
        } else {
            sensorPowerOff();
        }

        result.value = pendingValue;
        result.isValid = true;
        result.status = CycleStatus::OK;
        result.acceptedSeriesCount = pendingSeries;
        measOk = true;
        sendOk = espOk && sendValue(pendingValue, scaledValidReadings(pendingSeries));
    } else {
        // Regularny cykl: pomiar PRZED wlaczeniem Wi-Fi (mniejszy pobor i brak zaklocen radiowych podczas pulseIn)
        initializeSensor();
        measOk = performMeasurement(result, false, acceptRiseNow);
        sensorPowerOff();

        espOk = initializeEspNow();  // takze po nieudanym pomiarze - potrzebne do wysylki logow
        if (!measOk) {
            failReason = measFailReason(result.status);
        } else {
            pendingValue = result.value;
            pendingSeries = result.acceptedSeriesCount;
            sendOk = espOk && sendValue(pendingValue, scaledValidReadings(pendingSeries));
        }
    }

    // ----- planowanie snu -----
    const uint32_t activeSec = millis() / 1000;
    uint64_t sleepSeconds = DEEP_SLEEP_SECONDS;

    if (!retryWake) {
        secondsToRegular = DEEP_SLEEP_SECONDS;  // liczone od konca tego pomiaru
    } else {
        secondsToRegular = (secondsToRegular > activeSec) ? (secondsToRegular - activeSec) : 0;
    }

    if (measOk && !sendOk) {
        failReason = espOk ? "NO_ACK" : "ESPNOW_INIT_FAIL";

        const uint8_t idx = retryWake ? pendingRetryIdx : 0;
        // Dluzsza awaria odbiornika: po FAILED_CYCLES_NO_RETRY nieudanych cyklach nie budz sie na ponowienia (oszczednosc baterii)
        const bool retriesAllowed = failedRegular < FAILED_CYCLES_NO_RETRY;
        if (retriesAllowed && idx < SEND_RETRY_COUNT &&
            secondsToRegular > SEND_RETRY_SCHEDULE_S[idx] + SEND_RETRY_MARGIN_S) {
            sleepSeconds = SEND_RETRY_SCHEDULE_S[idx];
            secondsToRegular -= (uint32_t)sleepSeconds;
            pendingSend = true;
            pendingRetryIdx = idx + 1;
            LOGM("[MAIN] Kolejne ponowienie za %u s\n", (unsigned)sleepSeconds);
        } else {
            // koniec ponawiania - nastepny budzik to regularny cykl pomiarowy
            pendingSend = false;
            pendingRetryIdx = 0;
            if (failedRegular < 250) failedRegular++;
            sleepSeconds = secondsToRegular > 10 ? secondsToRegular : 10;
            LOGM("[MAIN] Koniec ponawiania - nastepny cykl za %u s (nieudanych cykli z rzedu: %u)\n",
                 (unsigned)sleepSeconds, (unsigned)failedRegular);
        }
    } else if (retryWake) {
        // ponowna wysylka udana - dospij do regularnego cyklu
        pendingSend = false;
        pendingRetryIdx = 0;
        sleepSeconds = secondsToRegular > 10 ? secondsToRegular : 10;
    }

    if (measOk && sendOk) {
        failedRegular = 0;
    }

    eventLogger.commitSession(measOk, sendOk, result, failReason);

    // ----- wysylka zapisanych cykli (logow) do odbiornika -----
    if (espOk && espNowManager->isReceiverKnown()) {
        LogSync::flush(*espNowManager, eventLogger, LOG_SYNC_BUDGET_MS);
    } else {
        DEBUG_PRINT("[LOGSYNC] Odbiornik niedostepny - logi zostana wyslane przy nastepnym kontakcie");
    }

    elapsedSincePrevWake = millis() / 1000 + (uint32_t)sleepSeconds;

    DEBUG_PRINT("\n[MAIN] Cykl zakonczony - ide spac");
    PowerManager::enterDeepSleep(sleepSeconds);
}

void loop() {
}
