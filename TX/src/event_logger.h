#ifndef EVENT_LOGGER_H
#define EVENT_LOGGER_H

#include <Arduino.h>
#include <FS.h>
#include "measurement.h"

// Log cykli na flash (LittleFS). Kazdy cykl to osobny plik /c<ID>.txt (skrot + pelny log sesji).
// Zachowywane jest ostatnie LOG_KEEP_CYCLES cykli. ID jest trwale (/meta.bin); razem z epoch
// (losowa wartosc nadawana przy utworzeniu meta) daje unikalny identyfikator rekordu do wysylki do odbiornika.
class EventLogger {
public:
    EventLogger();

    bool begin();
    bool isMounted() const { return _mounted; }

    void beginSession(const char* bootReason, float refValue);
    void logf(const char* fmt, ...);
    void commitSession(bool measOk, bool sendOk, const MeasurementResult& result, const char* failReason);

    // --- wysylka do odbiornika ---
    uint32_t epoch() const { return _meta.epoch; }
    bool nextUnsentId(uint32_t& id);                        // najstarszy rekord z ID > sentId
    void recordPath(uint32_t id, char* out, size_t cap) const;
    void markSent(uint32_t id);

private:
    struct Meta {
        uint32_t magic;
        uint32_t epoch;
        uint32_t nextId;
        uint32_t sentId;
        uint32_t checksum;
    };

    static const size_t MAX_IDS = 96;

    bool _mounted = false;
    bool _sessionActive = false;
    uint32_t _currentCycle = 0;
    const char* _bootReason = "UNKNOWN";
    char _sessionBuffer[LOG_SESSION_BUFFER_SIZE];
    size_t _sessionPos = 0;
    Meta _meta;

    bool loadMeta();
    void saveMeta();
    void initMeta();
    size_t listIds(uint32_t* out, size_t cap) const;        // rosnaco
    static bool parseId(const char* name, uint32_t& id);
    void pruneOld(uint32_t newestId);
    void ensureFreeSpace(size_t needed);
    bool writeRecord(uint32_t id, const char* summary, size_t summaryLen);
    void removeLegacyFiles();
};

extern EventLogger eventLogger;

#endif
