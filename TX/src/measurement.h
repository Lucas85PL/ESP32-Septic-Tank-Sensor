#ifndef MEASUREMENT_H
#define MEASUREMENT_H

#include <Arduino.h>
#include <vector>
#include <algorithm>
#include <math.h>
#include "config.h"
#include "ultrasonic_sensor.h"

class EventLogger;

enum class CycleStatus : uint8_t {
    OK,               // wynik wiarygodny i zaakceptowany
    BELOW_MIN_RANGE,  // poziom w strefie martwej czujnika (< 25 cm) - wynik = MIN_VALID_DISTANCE
    NO_VALID,         // brak klastra (bledy czujnika / czujnik wyjety) - nic nie wysylamy
    REJECTED_JUMP     // wiarygodny cykl, ale zmiana poza oknem czasowym - czeka na kolejny cykl
};

// Stan odniesienia miedzy cyklami - trzymany w RTC (przezywa deep sleep) i w flash (przezywa reset/utrate zasilania).
// Aktualizowany przy akceptacji pomiaru, NIEZALEZNIE od tego, czy odbiornik potwierdzil ACK.
struct RefState {
    float value;              // ostatni zaakceptowany wynik [cm]
    bool valid;               // false = brak odniesienia -> pierwszy wiarygodny cykl jest bootstrapem
    uint32_t secondsSinceRef; // rzeczywisty czas [s] od ostatniej aktualizacji (rozszerza okno napelniania; liczony tez przy ponowieniach)
    uint8_t rejectedCycles;   // ile kolejnych REGULARNYCH wiarygodnych cykli odrzucono jako skok
    uint8_t deadzoneCycles;   // ile kolejnych REGULARNYCH cykli wykryto strefe martwa (< 25 cm)
    uint8_t risePending;      // 1 = zaobserwowano wzrost odleglosci (wywoz) i czekamy na potwierdzenie w kolejnym cyklu
    float riseValue;          // wartosc kandydata na wywoz [cm]
};

struct MeasurementResult {
    float value;
    bool isValid;
    CycleStatus status;
    uint8_t acceptedSeriesCount;  // ile serii zgodnych z klastrem (z SERIES_COUNT)
};

class MeasurementManager {
public:
    // isRetry = pomiar przy ponowieniu wysylki (nie jest regularnym cyklem: nie zwieksza licznikow odrzuconych/strefy martwej)
    // acceptRiseNow = pierwszy cykl po fizycznym resecie TX: wzrost odleglosci (wywoz) przyjmowany bez potwierdzenia
    MeasurementManager(UltrasonicSensor& sensor, RefState& ref, EventLogger* logger = nullptr, bool isRetry = false,
                       bool acceptRiseNow = false);
    MeasurementResult performFullMeasurementCycle();

private:
    struct SampleStats {
        uint16_t total;
        uint16_t valid;
        uint16_t belowMin;
        uint16_t aboveMax;
        uint16_t timeouts;
        float belowSum;    // suma i suma kwadratow odczytow < MIN_VALID_DISTANCE (rozrzut strefy martwej)
        float belowSumSq;
    };

    struct Sample {
        float value;
        uint8_t series;
    };

    struct Cluster {
        uint16_t count;
        float median;
        float lo;
        float hi;
        uint8_t seriesCount;  // ile roznych serii ma probki w klastrze
    };

    UltrasonicSensor& _sensor;
    RefState& _ref;
    EventLogger* _logger;
    bool _isRetry;
    bool _acceptRiseNow;

    void performOneSeries(uint8_t seriesIdx, std::vector<Sample>& pool, SampleStats& stats);
    float calculateMedian(std::vector<float>& values);
    std::vector<Cluster> findClusters(std::vector<Sample> samples);
    bool evaluateConsensus(const std::vector<Sample>& pool, float& value, uint8_t& agreeingSeries);
    float fillWindowCm(float ratePerDay) const;
    bool isWithinAllowedChange(float value) const;
    void acceptValue(float value);
};

#endif
