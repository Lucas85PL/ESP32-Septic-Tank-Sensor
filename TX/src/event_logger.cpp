#include "event_logger.h"
#include <LittleFS.h>
#include <stdarg.h>
#include <cstring>
#include <stddef.h>
#include <algorithm>

EventLogger eventLogger;

namespace {
    const uint32_t META_MAGIC = 0x4D455441;  // "META"

    uint32_t fnv1a(const uint8_t* p, size_t len) {
        uint32_t sum = 2166136261u;
        for (size_t i = 0; i < len; i++) {
            sum ^= p[i];
            sum *= 16777619u;
        }
        return sum;
    }
}

EventLogger::EventLogger() {
    _sessionBuffer[0] = '\0';
    memset(&_meta, 0, sizeof(_meta));
}

// ---------------------------------------------------------------- mount / meta

bool EventLogger::begin() {
    LittleFS.end();

    _mounted = LittleFS.begin(false, "/littlefs", 10, LOG_PARTITION_LABEL);
    if (!_mounted) {
        DEBUG_PRINT("[LOG] Mount nieudany - formatuje partycje logow...");
        LittleFS.end();

        if (!LittleFS.format()) {
            DEBUG_PRINT("[LOG] BLAD: Format LittleFS nieudany");
            return false;
        }

        _mounted = LittleFS.begin(false, "/littlefs", 10, LOG_PARTITION_LABEL);
        if (!_mounted) {
            DEBUG_PRINT("[LOG] BLAD: Mount po formacie nieudany");
            return false;
        }
        DEBUG_PRINT("[LOG] LittleFS sformatowany i gotowy");
    } else {
        DEBUG_PRINT("[LOG] LittleFS gotowy");
    }

    removeLegacyFiles();

    if (!loadMeta()) {
        initMeta();
    }

    // meta mogla nie nadazyc za plikiem (przerwanie zapisu) - nigdy nie uzywaj ID, ktore juz istnieje
    uint32_t ids[MAX_IDS];
    size_t n = listIds(ids, MAX_IDS);
    if (n > 0 && ids[n - 1] >= _meta.nextId) {
        _meta.nextId = ids[n - 1] + 1;
        saveMeta();
    }

    DEBUG_PRINTF("[LOG] epoch=%08X nextId=%u sentId=%u rekordow=%u\n",
                 (unsigned)_meta.epoch, (unsigned)_meta.nextId, (unsigned)_meta.sentId, (unsigned)n);
    return true;
}

// Usuwa pozostalosci po poprzednich wersjach (/log.txt) i niedokonczone zapisy (c*.tmp).
void EventLogger::removeLegacyFiles() {
    LittleFS.remove("/log.txt");
    LittleFS.remove("/log.tmp");

    char tmpNames[8][24];
    size_t tmpCount = 0;
    File root = LittleFS.open("/");
    if (root && root.isDirectory()) {
        File e = root.openNextFile();
        while (e) {
            const char* name = e.name();
            const char* slash = name ? strrchr(name, '/') : nullptr;
            const char* base = slash ? slash + 1 : name;
            size_t len = base ? strlen(base) : 0;
            if (len > 4 && base[0] == 'c' && strcmp(base + len - 4, ".tmp") == 0 &&
                tmpCount < 8 && len < sizeof(tmpNames[0]) - 1) {
                snprintf(tmpNames[tmpCount++], sizeof(tmpNames[0]), "/%s", base);
            }
            e.close();
            e = root.openNextFile();
        }
        root.close();
    }
    for (size_t i = 0; i < tmpCount; i++) {
        LittleFS.remove(tmpNames[i]);
    }
}

bool EventLogger::loadMeta() {
    if (!LittleFS.exists(LOG_META_PATH)) return false;

    File f = LittleFS.open(LOG_META_PATH, "r");
    if (!f) return false;

    Meta m;
    size_t n = f.read((uint8_t*)&m, sizeof(m));
    f.close();

    if (n != sizeof(m) || m.magic != META_MAGIC ||
        m.checksum != fnv1a((const uint8_t*)&m, offsetof(Meta, checksum)) ||
        m.nextId < 1 || m.epoch == 0) {
        DEBUG_PRINT("[LOG] meta.bin uszkodzony - inicjalizuje od nowa");
        return false;
    }

    _meta = m;
    return true;
}

void EventLogger::saveMeta() {
    if (!_mounted) return;

    _meta.magic = META_MAGIC;
    _meta.checksum = fnv1a((const uint8_t*)&_meta, offsetof(Meta, checksum));

    File f = LittleFS.open(LOG_META_PATH, "w");
    if (!f) {
        DEBUG_PRINT("[LOG] BLAD: nie mozna zapisac meta.bin");
        return;
    }
    f.write((const uint8_t*)&_meta, sizeof(_meta));
    f.flush();
    f.close();
}

// Nowa epoka: wszystkie istniejace rekordy zostana (ponownie) wyslane pod nowym identyfikatorem.
void EventLogger::initMeta() {
    uint32_t ids[MAX_IDS];
    size_t n = listIds(ids, MAX_IDS);

    uint32_t epoch = 0;
    while (epoch == 0) epoch = esp_random();

    _meta.epoch = epoch;
    _meta.nextId = n > 0 ? ids[n - 1] + 1 : 1;
    _meta.sentId = n > 0 && ids[0] > 0 ? ids[0] - 1 : 0;
    saveMeta();
}

// ---------------------------------------------------------------- lista rekordow

bool EventLogger::parseId(const char* name, uint32_t& id) {
    if (!name) return false;
    const char* slash = strrchr(name, '/');
    const char* p = slash ? slash + 1 : name;
    if (*p != 'c') return false;
    p++;
    if (*p < '0' || *p > '9') return false;

    uint32_t v = 0;
    while (*p >= '0' && *p <= '9') {
        v = v * 10 + (uint32_t)(*p - '0');
        p++;
    }
    if (strcmp(p, ".txt") != 0) return false;
    id = v;
    return true;
}

void EventLogger::recordPath(uint32_t id, char* out, size_t cap) const {
    snprintf(out, cap, "/c%u.txt", (unsigned)id);
}

size_t EventLogger::listIds(uint32_t* out, size_t cap) const {
    size_t count = 0;
    File root = LittleFS.open("/");
    if (!root || !root.isDirectory()) return 0;

    File e = root.openNextFile();
    while (e) {
        uint32_t id;
        if (parseId(e.name(), id) && count < cap) {
            out[count++] = id;
        }
        e.close();
        e = root.openNextFile();
    }
    root.close();

    std::sort(out, out + count);
    return count;
}

bool EventLogger::nextUnsentId(uint32_t& id) {
    if (!_mounted) return false;
    uint32_t ids[MAX_IDS];
    size_t n = listIds(ids, MAX_IDS);
    for (size_t i = 0; i < n; i++) {
        if (ids[i] > _meta.sentId) {
            id = ids[i];
            return true;
        }
    }
    return false;
}

void EventLogger::markSent(uint32_t id) {
    if (id > _meta.sentId) {
        _meta.sentId = id;
        saveMeta();
    }
}

// Zostaw tylko ostatnie LOG_KEEP_CYCLES rekordow.
void EventLogger::pruneOld(uint32_t newestId) {
    (void)newestId;
    uint32_t ids[MAX_IDS];
    size_t n = listIds(ids, MAX_IDS);
    char path[24];
    for (size_t i = 0; n - i > LOG_KEEP_CYCLES; i++) {
        recordPath(ids[i], path, sizeof(path));
        LittleFS.remove(path);
    }
}

// Gdy w partycji brakuje miejsca, usuwaj najstarsze rekordy (nawet niewyslane) - log nie moze zablokowac pomiarow.
void EventLogger::ensureFreeSpace(size_t needed) {
    for (int guard = 0; guard < 100; guard++) {
        size_t total = LittleFS.totalBytes();
        size_t used = LittleFS.usedBytes();
        size_t freeBytes = total > used ? total - used : 0;
        if (freeBytes >= needed + LOG_MIN_FREE_BYTES) return;

        uint32_t ids[MAX_IDS];
        size_t n = listIds(ids, MAX_IDS);
        if (n == 0) return;

        char path[24];
        recordPath(ids[0], path, sizeof(path));
        LittleFS.remove(path);
        DEBUG_PRINTF("[LOG] Brak miejsca - usunieto najstarszy rekord %u\n", (unsigned)ids[0]);
    }
}

// ---------------------------------------------------------------- sesja

void EventLogger::beginSession(const char* bootReason, float refValue) {
    _currentCycle = _meta.nextId;
    _bootReason = bootReason ? bootReason : "UNKNOWN";
    _sessionPos = 0;
    _sessionBuffer[0] = '\0';
    _sessionActive = true;

    logf("--- SESSION CYCLE=%u BEGIN | WAKE=%s | ref=%.2f ---\n",
         (unsigned)_currentCycle, _bootReason, refValue);
}

void EventLogger::logf(const char* fmt, ...) {
    if (!_sessionActive || _sessionPos >= LOG_SESSION_BUFFER_SIZE - 1) {
        return;
    }

    va_list args;
    va_start(args, fmt);
    int written = vsnprintf(_sessionBuffer + _sessionPos,
                            LOG_SESSION_BUFFER_SIZE - _sessionPos,
                            fmt, args);
    va_end(args);

    if (written > 0) {
        size_t space = LOG_SESSION_BUFFER_SIZE - _sessionPos - 1;
        size_t toAdd = (size_t)written < space ? (size_t)written : space;
        _sessionPos += toAdd;
        _sessionBuffer[_sessionPos] = '\0';
    }
}

// Zapis atomowy: najpierw plik tymczasowy, potem rename.
bool EventLogger::writeRecord(uint32_t id, const char* summary, size_t summaryLen) {
    char tmpPath[24];
    char path[24];
    snprintf(tmpPath, sizeof(tmpPath), "/c%u.tmp", (unsigned)id);
    recordPath(id, path, sizeof(path));

    File f = LittleFS.open(tmpPath, "w");
    if (!f) {
        DEBUG_PRINT("[LOG] BLAD: Nie mozna zapisac rekordu");
        return false;
    }

    bool ok = f.write((const uint8_t*)summary, summaryLen) == summaryLen;
    if (ok && _sessionPos > 0) {
        ok = f.write((const uint8_t*)_sessionBuffer, _sessionPos) == _sessionPos;
    }
    f.flush();
    f.close();

    if (!ok) {
        DEBUG_PRINT("[LOG] BLAD: zapis rekordu niepelny (brak miejsca?)");
        LittleFS.remove(tmpPath);
        return false;
    }

    LittleFS.remove(path);
    if (!LittleFS.rename(tmpPath, path)) {
        DEBUG_PRINT("[LOG] BLAD: rename rekordu nieudany");
        LittleFS.remove(tmpPath);
        return false;
    }
    return true;
}

void EventLogger::commitSession(bool measOk, bool sendOk, const MeasurementResult& result,
                                const char* failReason) {
    if (!_sessionActive) return;

    logf("--- SESSION CYCLE=%u END ---\n", (unsigned)_currentCycle);
    _sessionActive = false;

    if (!_mounted) return;

    char summary[256];
    int summaryLen;

    if (measOk && result.isValid) {
        summaryLen = snprintf(summary, sizeof(summary),
            "CYCLE=%u | WAKE=%s | valid=1 | result=%.2f | series=%u/%d | send=%s%s%s\n",
            (unsigned)_currentCycle,
            _bootReason,
            result.value,
            (unsigned)result.acceptedSeriesCount,
            SERIES_COUNT,
            sendOk ? "OK" : "FAIL",
            (!sendOk && failReason) ? " | reason=" : "",
            (!sendOk && failReason) ? failReason : "");
    } else {
        const char* reason = failReason ? failReason : "UNKNOWN";
        summaryLen = snprintf(summary, sizeof(summary),
            "CYCLE=%u | WAKE=%s | valid=0 | result=--- | series=%u/%d | send=%s | reason=%s\n",
            (unsigned)_currentCycle,
            _bootReason,
            measOk ? (unsigned)result.acceptedSeriesCount : 0U,
            SERIES_COUNT,
            measOk ? (sendOk ? "OK" : "FAIL") : "SKIP",
            reason);
    }

    if (summaryLen <= 0) return;
    if ((size_t)summaryLen >= sizeof(summary)) summaryLen = sizeof(summary) - 1;

    ensureFreeSpace((size_t)summaryLen + _sessionPos + 512);

    if (writeRecord(_currentCycle, summary, (size_t)summaryLen)) {
        _meta.nextId = _currentCycle + 1;
        saveMeta();
        pruneOld(_currentCycle);
        DEBUG_PRINTF("[LOG] Cykl %u zapisany do flash\n", (unsigned)_currentCycle);
    }
}
