#ifndef LOG_SYNC_H
#define LOG_SYNC_H

#include <Arduino.h>
#include "espnow_manager.h"
#include "event_logger.h"

// Wysylka zapisanych cykli (rekordow logu) do odbiornika. Kazdy rekord to plik /c<ID>.txt dzielony na porcje
// po LOG_CHUNK_DATA_MAX bajtow; kazda porcja jest potwierdzana przez odbiornik (protokol: log_protocol.h).
// Rekord jest oznaczany jako wyslany dopiero po potwierdzeniu ostatniej porcji, wiec przerwana wysylka
// (brak odbiornika, limit czasu) jest wznawiana przy nastepnym wybudzeniu.
namespace LogSync {
    // Zwraca liczbe w pelni wyslanych rekordow. Wymaga znanego odbiornika (net.isReceiverKnown()).
    uint16_t flush(EspNowManager& net, EventLogger& log, uint32_t budgetMs);
}

#endif
