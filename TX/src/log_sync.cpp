#include "log_sync.h"
#include <LittleFS.h>

namespace {
    enum class RecordOutcome { SENT, SKIPPED, ABORT };

    // Punkt wznowienia przerwanego rekordu (RTC - przezywa deep sleep). To tylko wskazowka: odbiornik i tak sprawdza
    // kolejnosc porcji i w razie niezgodnosci odpowiada RESTART z numerem porcji, od ktorej nalezy kontynuowac.
    RTC_DATA_ATTR uint32_t s_resumeEpoch = 0;
    RTC_DATA_ATTR uint32_t s_resumeId = 0;
    RTC_DATA_ATTR uint16_t s_resumeSeq = 0;
    const uint8_t MAX_RESTARTS = 2;

    RecordOutcome sendRecord(EspNowManager& net, EventLogger& log, uint32_t id,
                             uint32_t startMs, uint32_t budgetMs) {
        char path[24];
        log.recordPath(id, path, sizeof(path));

        File f = LittleFS.open(path, "r");
        if (!f) return RecordOutcome::SKIPPED;

        const size_t size = f.size();
        if (size == 0) {
            f.close();
            return RecordOutcome::SKIPPED;
        }

        const uint16_t total = (uint16_t)((size + LOG_CHUNK_DATA_MAX - 1) / LOG_CHUNK_DATA_MAX);
        uint16_t seq = 0;
        if (s_resumeEpoch == log.epoch() && s_resumeId == id && s_resumeSeq > 0 && s_resumeSeq < total) {
            seq = s_resumeSeq;  // wznow od miejsca, w ktorym poprzednia wysylka zostala przerwana
        }
        uint8_t restarts = 0;
        RecordOutcome outcome = RecordOutcome::SENT;

        while (seq < total) {
            if ((uint32_t)(millis() - startMs) >= budgetMs) {
                outcome = RecordOutcome::ABORT;
                break;
            }

            LogChunkPacket pkt;
            pkt.magic = LOG_CHUNK_MAGIC;
            pkt.epoch = log.epoch();
            pkt.cycleId = id;
            pkt.seq = seq;
            pkt.total = total;

            f.seek((size_t)seq * LOG_CHUNK_DATA_MAX);
            size_t n = f.read(pkt.data, LOG_CHUNK_DATA_MAX);
            if (n == 0) {
                outcome = RecordOutcome::SKIPPED;
                break;
            }
            pkt.len = (uint8_t)n;

            uint16_t rxNext = 0;
            LogChunkResult r = net.sendLogChunk(pkt, LOG_CHUNK_HEADER_SIZE + n, &rxNext);
            if (r == LogChunkResult::OK) {
                seq++;
            } else if (r == LogChunkResult::RESTART && restarts++ < MAX_RESTARTS) {
                seq = (rxNext < total) ? rxNext : 0;  // odbiornik wskazuje, od ktorej porcji kontynuowac
            } else if (r == LogChunkResult::REJECT) {
                outcome = RecordOutcome::SKIPPED;
                break;
            } else {
                outcome = RecordOutcome::ABORT;
                break;
            }
        }

        f.close();
        if (outcome == RecordOutcome::ABORT) {
            s_resumeEpoch = log.epoch();
            s_resumeId = id;
            s_resumeSeq = seq;
        } else {
            s_resumeEpoch = 0;
            s_resumeId = 0;
            s_resumeSeq = 0;
        }
        return outcome;
    }
}

uint16_t LogSync::flush(EspNowManager& net, EventLogger& log, uint32_t budgetMs) {
    if (!log.isMounted() || !net.isReceiverKnown()) return 0;

    const uint32_t startMs = millis();
    uint16_t sent = 0;
    uint32_t id;

    DEBUG_PRINT("\n========== WYSYLKA LOGOW DO ODBIORNIKA ==========");
    while (log.nextUnsentId(id)) {
        RecordOutcome r = sendRecord(net, log, id, startMs, budgetMs);
        if (r == RecordOutcome::ABORT) {
            DEBUG_PRINTF("[LOGSYNC] Przerwano na rekordzie %u (wyslano %u) - reszta przy nastepnym wybudzeniu\n",
                         (unsigned)id, (unsigned)sent);
            return sent;
        }
        log.markSent(id);
        if (r == RecordOutcome::SENT) {
            sent++;
            DEBUG_PRINTF("[LOGSYNC] Rekord %u wyslany\n", (unsigned)id);
        } else {
            DEBUG_PRINTF("[LOGSYNC] Rekord %u pominiety\n", (unsigned)id);
        }
    }

    DEBUG_PRINTF("[LOGSYNC] Gotowe: wyslano %u rekordow w %lu ms\n", (unsigned)sent, (unsigned long)(millis() - startMs));
    return sent;
}
