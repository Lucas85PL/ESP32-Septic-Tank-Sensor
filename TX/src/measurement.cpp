#include "measurement.h"
#include "config.h"
#include "event_logger.h"

#define MEAS_LOG(x) do { DEBUG_PRINT(x); if (_logger) _logger->logf("%s\n", x); } while(0)
#define MEAS_LOGF(...) do { DEBUG_PRINTF(__VA_ARGS__); if (_logger) _logger->logf(__VA_ARGS__); } while(0)

MeasurementManager::MeasurementManager(UltrasonicSensor& sensor, RefState& ref, EventLogger* logger, bool isRetry,
                                       bool acceptRiseNow)
    : _sensor(sensor)
    , _ref(ref)
    , _logger(logger)
    , _isRetry(isRetry)
    , _acceptRiseNow(acceptRiseNow) {
}

float MeasurementManager::calculateMedian(std::vector<float>& values) {
    if (values.empty()) return INVALID_READING;

    std::sort(values.begin(), values.end(), [](float a, float b) { return a < b; });

    size_t size = values.size();
    if (size % 2 == 0) {
        return (values[size/2 - 1] + values[size/2]) / 2.0f;
    } else {
        return values[size/2];
    }
}

// Pojedyncza seria: kazdy odczyt klasyfikowany jako poprawny / ponizej zakresu / powyzej zakresu / timeout.
// Poprawne probki trafiaja do wspolnej puli cyklu (z numerem serii).
void MeasurementManager::performOneSeries(uint8_t seriesIdx, std::vector<Sample>& pool, SampleStats& stats) {
    for (int i = 0; i < MEASUREMENTS_PER_SERIES; i++) {
        float distance = _sensor.measureDistanceCm();
        stats.total++;

        if (distance < 0) {
            stats.timeouts++;
            MEAS_LOGF("[POMIAR] %d: TIMEOUT\n", i + 1);
        } else if (distance < MIN_VALID_DISTANCE) {
            stats.belowMin++;
            stats.belowSum += distance;
            stats.belowSumSq += distance * distance;
            MEAS_LOGF("[POMIAR] %d: %.2f cm ODRZUCONY (< %.0f)\n", i + 1, distance, MIN_VALID_DISTANCE);
        } else if (distance > MAX_VALID_DISTANCE) {
            stats.aboveMax++;
            MEAS_LOGF("[POMIAR] %d: %.2f cm ODRZUCONY (> %.0f)\n", i + 1, distance, MAX_VALID_DISTANCE);
        } else {
            stats.valid++;
            Sample s = { distance, seriesIdx };
            pool.push_back(s);
            MEAS_LOGF("[POMIAR] %d: %.2f cm\n", i + 1, distance);
        }

        if (i < MEASUREMENTS_PER_SERIES - 1) {
            delay(MEASUREMENT_INTERVAL_MS);
        }
    }
}

// Zachlanne wyszukiwanie najgestszych okien (szerokosc 2 x POOL_HALF_WIDTH_CM) w puli probek.
// Zwraca do POOL_MAX_CLUSTERS klastrow, od najwiekszego.
std::vector<MeasurementManager::Cluster> MeasurementManager::findClusters(std::vector<Sample> samples) {
    std::vector<Cluster> clusters;
    std::sort(samples.begin(), samples.end(),
              [](const Sample& a, const Sample& b) { return a.value < b.value; });

    const float width = 2.0f * POOL_HALF_WIDTH_CM;

    for (int c = 0; c < POOL_MAX_CLUSTERS && !samples.empty(); c++) {
        size_t bestStart = 0;
        size_t bestCount = 0;

        for (size_t i = 0; i < samples.size(); i++) {
            size_t j = i;
            while (j < samples.size() && samples[j].value <= samples[i].value + width) {
                j++;
            }
            if (j - i > bestCount) {
                bestStart = i;
                bestCount = j - i;
            }
        }

        std::vector<float> values;
        values.reserve(bestCount);
        uint16_t seriesMask = 0;
        for (size_t k = bestStart; k < bestStart + bestCount; k++) {
            values.push_back(samples[k].value);
            seriesMask |= (uint16_t)(1u << samples[k].series);
        }

        Cluster cl;
        cl.count = (uint16_t)bestCount;
        cl.lo = samples[bestStart].value;
        cl.hi = samples[bestStart + bestCount - 1].value;
        cl.median = calculateMedian(values);
        cl.seriesCount = 0;
        for (; seriesMask; seriesMask >>= 1) cl.seriesCount += seriesMask & 1u;
        clusters.push_back(cl);

        samples.erase(samples.begin() + bestStart, samples.begin() + bestStart + bestCount);
    }

    return clusters;
}

// Konsensus cyklu na poziomie probek.
// - klastry mniejsze niz POOL_MIN_SAMPLES sa odrzucane,
// - gdy jest odniesienie: wybierany jest najwiekszy klaster ZGODNY z oczekiwanym zakresem
//   (okno napelniania zalezne od czasu albo wywoz),
// - w przeciwnym razie najwiekszy klaster, o ile dominuje nad drugim (POOL_DOMINANCE_RATIO).
bool MeasurementManager::evaluateConsensus(const std::vector<Sample>& pool, float& value, uint8_t& agreeingSeries) {
    agreeingSeries = 0;
    if (pool.empty()) return false;

    std::vector<Cluster> all = findClusters(pool);
    std::vector<Cluster> clusters;
    for (const Cluster& cl : all) {
        MEAS_LOGF("[KLASTER] %d probek w %d seriach, mediana %.2f cm (%.2f-%.2f)\n",
                  (int)cl.count, (int)cl.seriesCount, cl.median, cl.lo, cl.hi);
        if (cl.count >= POOL_MIN_SAMPLES) {
            clusters.push_back(cl);
        }
    }

    const Cluster* chosen = nullptr;

    // klaster zgodny z oczekiwanym zakresem: nizszy prog probek, ale wymagane wsparcie z wielu serii
    if (_ref.valid) {
        for (const Cluster& cl : all) {
            if (cl.count >= POOL_PRIOR_MIN_SAMPLES && cl.seriesCount >= POOL_PRIOR_MIN_SERIES &&
                isWithinAllowedChange(cl.median)) {
                chosen = &cl;
                break;
            }
        }
    }

    if (chosen == nullptr && clusters.empty()) return false;

    if (chosen == nullptr) {  // clusters nie jest puste (sprawdzone wyzej)
        const Cluster& top = clusters[0];
        uint16_t second = clusters.size() > 1 ? clusters[1].count : 0;
        if (top.count >= POOL_DOMINANCE_RATIO * second) {
            chosen = &top;
        }
    }

    if (chosen == nullptr) return false;

    // ile serii ma co najmniej POOL_SERIES_MIN_SAMPLES probek w wybranym oknie (do validReadings)
    uint8_t perSeries[SERIES_COUNT] = {0};
    for (const Sample& s : pool) {
        if (s.value >= chosen->lo && s.value <= chosen->hi && s.series < SERIES_COUNT) {
            perSeries[s.series]++;
        }
    }
    for (int i = 0; i < SERIES_COUNT; i++) {
        if (perSeries[i] >= POOL_SERIES_MIN_SAMPLES) agreeingSeries++;
    }

    value = chosen->median;
    return true;
}

// Walidacja miedzy cyklami zalezna od CZASU od ostatniej aktualizacji odniesienia.
// - spadek odleglosci (napelnianie): dozwolony do FILL_MAX_CM_PER_DAY * dni + szum
// - wzrost odleglosci (oproznianie): szum albo wynik >= EMPTY_ZONE_MIN (wywoz)
float MeasurementManager::fillWindowCm(float ratePerDay) const {
    float elapsedDays = (float)_ref.secondsSinceRef / 86400.0f;
    return ratePerDay * elapsedDays + RISE_NOISE_CM;
}

bool MeasurementManager::isWithinAllowedChange(float value) const {
    // tuz nad strefa martwa poziom rosnie wolniej - waskie okno utrudnia przyjecie falszywego echa
    float rate = (value < MIN_VALID_DISTANCE + SLOW_FILL_ZONE_CM) ? SLOW_FILL_MAX_CM_PER_DAY : FILL_MAX_CM_PER_DAY;
    float fillWindow = fillWindowCm(rate);
    float delta = value - _ref.value;

    if (delta > RISE_NOISE_CM) {
        return value >= EMPTY_ZONE_MIN;
    }
    return delta >= -fillWindow;
}

void MeasurementManager::acceptValue(float value) {
    _ref.value = value;
    _ref.valid = true;
    _ref.secondsSinceRef = 0;
    _ref.rejectedCycles = 0;
    _ref.deadzoneCycles = 0;
    _ref.risePending = 0;
}

MeasurementResult MeasurementManager::performFullMeasurementCycle() {
    MEAS_LOG("========================================");
    MEAS_LOG("[CYKL] Rozpoczynam cykl pomiarowy");
    MEAS_LOGF("[CYKL] %d serii po %d pomiarow\n", SERIES_COUNT, MEASUREMENTS_PER_SERIES);
    MEAS_LOGF("[CYKL] Zakres: %.0f-%.0f cm\n", MIN_VALID_DISTANCE, MAX_VALID_DISTANCE);
    MEAS_LOGF("[CYKL] Odniesienie: %.2f cm (valid=%d, %.1f h od aktualizacji, odrzuconych=%d)%s\n",
              _ref.value, _ref.valid ? 1 : 0, _ref.secondsSinceRef / 3600.0f, (int)_ref.rejectedCycles,
              _isRetry ? " [ponowienie]" : "");
    MEAS_LOG("========================================");

    MeasurementResult result = {};
    result.value = INVALID_READING;
    result.status = CycleStatus::NO_VALID;

    std::vector<Sample> pool;
    pool.reserve(TOTAL_MEASUREMENTS);
    SampleStats stats = {};

    // Wszystkie serie zawsze sie wykonuja (stale odstepy w czasie) - ocena dopiero po zebraniu.
    for (int series = 0; series < SERIES_COUNT; series++) {
        MEAS_LOGF("\n[SERIA %d/%d] Start\n", series + 1, SERIES_COUNT);
        performOneSeries((uint8_t)series, pool, stats);

        if (series < SERIES_COUNT - 1) {
            delay(SERIES_INTERVAL_MS);
        }
    }

    MEAS_LOG("\n========================================");
    MEAS_LOGF("[CYKL] Probki: poprawne %d, <min %d, >max %d, timeout %d (z %d)\n",
              (int)stats.valid, (int)stats.belowMin, (int)stats.aboveMax, (int)stats.timeouts, (int)stats.total);

    float cycleValue = INVALID_READING;
    uint8_t agreeing = 0;
    bool reliable = evaluateConsensus(pool, cycleValue, agreeing);
    MEAS_LOGF("[CYKL] Konsensus: %s\n", reliable ? "WIARYGODNY" : "NIEWIARYGODNY");

    if (!reliable) {
        // Strefa martwa: poziom wszedl ponizej 25 cm, wiekszosc probek poza zakresem od dolu,
        // a poprzedni wynik byl niski (zbiornik prawie pelny).
        bool mostlyBelowMin = stats.total > 0 &&
                              (uint32_t)stats.belowMin * 100 >= (uint32_t)DEADZONE_MIN_RATIO_PCT * stats.total;
        // Strefa martwa tylko gdy odniesienie mogloby tam dojsc w czasie, ktory uplynal (okno napelniania);
        // inaczej to blad czujnika (skropliny, falszywe echo), a nie pelny zbiornik.
        float dzWindow = fillWindowCm(SLOW_FILL_MAX_CM_PER_DAY);
        bool deadzonePlausible = _ref.valid &&
            (_ref.value - dzWindow) <= MIN_VALID_DISTANCE + DEADZONE_PLAUSIBLE_MARGIN_CM;
        // Prawdziwy czujnik w strefie martwej daje rozproszone odczyty; stabilna wartosc to falszywe echo.
        float belowSpread = 0.0f;
        if (stats.belowMin > 1) {
            float mean = stats.belowSum / stats.belowMin;
            float var = stats.belowSumSq / stats.belowMin - mean * mean;
            belowSpread = var > 0.0f ? sqrtf(var) : 0.0f;
        }
        bool spreadOk = belowSpread >= DEADZONE_MIN_SPREAD_CM;
        if (mostlyBelowMin && _ref.valid && _ref.value <= DEADZONE_LAST_MAX_CM && (!deadzonePlausible || !spreadOk)) {
            MEAS_LOGF("[WYNIK] Strefa martwa odrzucona (odniesienie %.2f, okno %.1f cm, rozrzut %.2f cm) - blad czujnika\n",
                      _ref.value, dzWindow, belowSpread);
        }
        if (mostlyBelowMin && deadzonePlausible && spreadOk && _ref.value <= DEADZONE_LAST_MAX_CM) {
            if (!_isRetry && _ref.deadzoneCycles < DEADZONE_CONFIRM_CYCLES) {
                _ref.deadzoneCycles++;
            }
            if (_ref.deadzoneCycles >= DEADZONE_CONFIRM_CYCLES) {
                MEAS_LOG("[WYNIK] Strefa martwa (< 25 cm) potwierdzona - wysylam wartosc minimalna czujnika");
                acceptValue(MIN_VALID_DISTANCE);
                _ref.deadzoneCycles = DEADZONE_CONFIRM_CYCLES;  // kolejne cykle w strefie martwej wysylaja od razu
                result.value = MIN_VALID_DISTANCE;
                result.isValid = true;
                result.status = CycleStatus::BELOW_MIN_RANGE;
                result.acceptedSeriesCount = DEADZONE_REPORTED_SERIES;
                return result;
            }
            MEAS_LOGF("[WYNIK] Strefa martwa - potwierdzenie %d/%d, na razie nic nie wysylam\n",
                      (int)_ref.deadzoneCycles, DEADZONE_CONFIRM_CYCLES);
            result.status = CycleStatus::NO_VALID;
            return result;
        }

        _ref.deadzoneCycles = 0;
        result.status = CycleStatus::NO_VALID;
        MEAS_LOG("[WYNIK] BLAD: brak wiarygodnego wyniku - nic nie wysylam");
        return result;
    }

    result.acceptedSeriesCount = agreeing;

    if (!_ref.valid) {
        MEAS_LOG("[CROSS] Bootstrap: brak wartosci referencyjnej - akceptuj wiarygodny cykl");
        acceptValue(cycleValue);
    } else if (isWithinAllowedChange(cycleValue)) {
        MEAS_LOGF("[CROSS] %.2f cm w dozwolonym zakresie wzgledem %.2f cm\n", cycleValue, _ref.value);
        if (cycleValue - _ref.value > RISE_NOISE_CM && !_acceptRiseNow) {
            // Wzrost odleglosci (wywoz): wymaga 2 kolejnych zgodnych cykli - pojedyncze falszywe echo (np. wyjety czujnik)
            // nie ustawi "pustego zbiornika". Retry (swiezy pomiar po braku ACK) nie potwierdza i nie ustawia kandydata.
            if (!_isRetry && _ref.risePending && fabsf(cycleValue - _ref.riseValue) <= RISE_CONFIRM_TOL_CM) {
                MEAS_LOGF("[CROSS] Wywoz potwierdzony drugim cyklem (%.2f cm, kandydat %.2f cm)\n", cycleValue, _ref.riseValue);
                acceptValue(cycleValue);
            } else {
                if (!_isRetry) {
                    _ref.risePending = 1;
                    _ref.riseValue = cycleValue;
                }
                _ref.deadzoneCycles = 0;
                result.status = CycleStatus::REJECTED_JUMP;
                MEAS_LOGF("[WYNIK] Wzrost odleglosci do %.2f cm - czekam na potwierdzenie w kolejnym cyklu\n", cycleValue);
                return result;
            }
        } else {
            acceptValue(cycleValue);
        }
    } else {
        MEAS_LOGF("[CROSS] %.2f cm poza dozwolonym zakresem wzgledem %.2f cm\n", cycleValue, _ref.value);
        if (cycleValue < MIN_VALID_DISTANCE + NEAR_MIN_MARGIN_CM) {
            // Podejrzane echo tuz nad strefa martwa - nie resetujemy odniesienia. Okno napelniania rosnie
            // z kazdym cyklem, wiec prawdziwy poziom zostanie zaakceptowany bez resetu.
            _ref.deadzoneCycles = 0;
            result.status = CycleStatus::NO_VALID;
            MEAS_LOGF("[WYNIK] %.2f cm tuz nad strefa martwa i poza oknem - podejrzane echo, nic nie wysylam\n", cycleValue);
            return result;
        }
        if (!_isRetry && _ref.rejectedCycles >= MAX_REJECTED_CYCLES) {
            MEAS_LOG("[CROSS] Skok utrzymuje sie (limit odrzuconych cykli) - akceptuj i resetuj odniesienie");
            acceptValue(cycleValue);
        } else {
            if (!_isRetry) {
                _ref.rejectedCycles++;
            }
            _ref.deadzoneCycles = 0;
            result.status = CycleStatus::REJECTED_JUMP;
            MEAS_LOGF("[WYNIK] Skok poza oknem (%.2f cm) - odrzucony %d/%d\n",
                      cycleValue, (int)_ref.rejectedCycles, MAX_REJECTED_CYCLES);
            return result;
        }
    }

    result.value = cycleValue;
    result.isValid = true;
    result.status = CycleStatus::OK;
    MEAS_LOGF("[WYNIK] Zaakceptowano: %.2f cm (zgodnych serii: %d)\n", cycleValue, (int)agreeing);
    return result;
}
