#ifndef MEAS_HISTORY_H
#define MEAS_HISTORY_H

#include <Arduino.h>
#include "measurement.h"
#include "meas_protocol.h"

// Historia zatwierdzonych pomiarow (do MEAS_HIST_MAX) wysylana do odbiornika razem z pomiarem.
// Stan w RTC (przezywa deep sleep) i w flash (/hist.bin, zapis atomowy tmp + rename, suma kontrolna) - przezywa reset zasilania.
// Historia jest czyszczona przy kazdym zaakceptowanym WZROSCIE odleglosci (wywoz) i przy resecie odniesienia po
// odrzuconych cyklach; sam reset TX jej nie czysci.
namespace MeasHistory {
    void resetRtc();                                  // czysty stan RTC (pierwszy start po wgraniu / smieci w RTC)
    void advanceClock(uint32_t elapsedSeconds);       // czas od poprzedniego wybudzenia (jak wiek odniesienia)
    void begin();                                     // po zamontowaniu LittleFS: po cold boot odtwarza historie z flash
    // Wolac po kazdym zaakceptowanym pomiarze (result.isValid). prev* = stan odniesienia PRZED pomiarem.
    void onAccepted(const MeasurementResult& result, bool prevValid, float prevValue, uint8_t prevRejected, bool isRetry);
    // Buduje pakiet; zwraca liczbe bajtow do wyslania. fallbackValue uzywane tylko, gdy historia jest pusta.
    size_t buildPacket(MeasurementPacketV2& packet, uint8_t validReadings, float fallbackValue);
    uint8_t count();
    uint32_t seq();
    uint32_t epoch();
}

#endif
