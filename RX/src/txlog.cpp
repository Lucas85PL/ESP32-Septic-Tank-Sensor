#include "txlog.h"
#include "espnow_receiver.h"
#include <LittleFS.h>
#include <Preferences.h>

TxLog txLog;
volatile bool g_serialQuiet = false;

#define TXLOG_NVS_NAMESPACE "txlog"

bool TxLog::begin() {
    _ok = LittleFS.begin(true);  // true = sformatuj przy pierwszym uzyciu
    if (!_ok) {
        DEBUG_PRINT("[TXLOG] BLAD: LittleFS niedostepny - logi TX nie beda zapisywane");
        return false;
    }

    Preferences prefs;
    if (prefs.begin(TXLOG_NVS_NAMESPACE, false)) {
        _lastValid = prefs.getBool("v", false);
        _lastEpoch = prefs.getUInt("ep", 0);
        _lastId = prefs.getUInt("id", 0);
        prefs.end();
    }

    DEBUG_PRINTF("[TXLOG] Gotowe (ostatni rekord: %s epoch=%08X id=%u). Komendy: TXLOG, TXLOG DUMP, TXLOG CLEAR\n",
                 _lastValid ? "tak" : "brak", (unsigned)_lastEpoch, (unsigned)_lastId);
    return true;
}

void TxLog::loop(EspNowReceiver& rx) {
    LogChunkSlot slot;
    if (rx.takeLogChunk(slot)) {
        handleChunk(rx, slot);
    }
    serviceSerial();
    serviceDump();
}

// ---------------------------------------------------------------- odbior porcji

void TxLog::sendAck(EspNowReceiver& rx, const uint8_t* mac, uint32_t epoch, uint32_t id, uint16_t seq, uint8_t status,
                    uint16_t nextSeq) {
    LogAckPacket ack;
    ack.magic = LOG_ACK_MAGIC;
    ack.epoch = epoch;
    ack.cycleId = id;
    ack.seq = seq;
    ack.status = status;
    ack.nextSeq = nextSeq;
    rx.sendLogAck(mac, ack);
}

void TxLog::handleChunk(EspNowReceiver& rx, const LogChunkSlot& s) {
    if (!_ok) return;  // bez potwierdzenia - nadajnik odpusci i sprobuje przy nastepnym wybudzeniu
    if (s.len <= LOG_CHUNK_HEADER_SIZE || s.len > sizeof(LogChunkPacket)) return;

    LogChunkPacket p;
    memset(&p, 0, sizeof(p));
    memcpy(&p, s.data, s.len);
    if (p.magic != LOG_CHUNK_MAGIC || p.len == 0 || p.len > LOG_CHUNK_DATA_MAX ||
        (size_t)LOG_CHUNK_HEADER_SIZE + p.len != s.len || p.total == 0 || p.seq >= p.total) {
        return;
    }

    // duplikat calego, juz zapisanego rekordu - potwierdz bez zapisu
    if (_lastValid && p.epoch == _lastEpoch && p.cycleId <= _lastId) {
        sendAck(rx, s.mac, p.epoch, p.cycleId, p.seq, LOG_ACK_OK, p.total);
        return;
    }

    if (p.seq == 0) {
        _active = true;
        _curEpoch = p.epoch;
        _curId = p.cycleId;
        _curTotal = p.total;
        _nextSeq = 0;
        _used = 0;
    }

    const bool sameRecord = _active && p.epoch == _curEpoch && p.cycleId == _curId;
    if (!sameRecord || p.seq != _nextSeq) {
        // powtorzona (juz przyjeta) porcja tego samego rekordu = OK, w innym wypadku nadawaj od poczatku
        uint8_t status = (sameRecord && p.seq < _nextSeq) ? LOG_ACK_OK : LOG_ACK_RESTART;
        // nextSeq: nadajnik moze wznowic rekord od miejsca, w ktorym stoimy (0 = nie znamy tego rekordu - od poczatku)
        sendAck(rx, s.mac, p.epoch, p.cycleId, p.seq, status, sameRecord ? _nextSeq : 0);
        return;
    }

    if (_used + p.len > sizeof(_rec)) {
        _active = false;
        sendAck(rx, s.mac, p.epoch, p.cycleId, p.seq, LOG_ACK_REJECT, 0);
        return;
    }

    memcpy(_rec + _used, p.data, p.len);
    _used += p.len;
    _nextSeq++;

    if (_nextSeq >= _curTotal) {
        bool saved = commitRecord();
        _active = false;
        sendAck(rx, s.mac, p.epoch, p.cycleId, p.seq, saved ? LOG_ACK_OK : LOG_ACK_RESTART, saved ? _curTotal : 0);
        return;
    }

    sendAck(rx, s.mac, p.epoch, p.cycleId, p.seq, LOG_ACK_OK, _nextSeq);
}

// Zapis kompletnego rekordu do /txlog.txt (z rotacja) i zapamietanie (epoch, id).
bool TxLog::commitRecord() {
    char header[64];
    int hlen = snprintf(header, sizeof(header), "##### RX epoch=%08X id=%u bytes=%u\n",
                        (unsigned)_curEpoch, (unsigned)_curId, (unsigned)_used);
    if (hlen <= 0) return false;

    size_t curSize = 0;
    if (LittleFS.exists(TXLOG_FILE_CUR)) {
        File f = LittleFS.open(TXLOG_FILE_CUR, "r");
        if (f) {
            curSize = f.size();
            f.close();
        }
    }
    if (curSize + _used + hlen > TXLOG_MAX_FILE_BYTES) {
        LittleFS.remove(TXLOG_FILE_OLD);
        LittleFS.rename(TXLOG_FILE_CUR, TXLOG_FILE_OLD);
    }

    File f = LittleFS.open(TXLOG_FILE_CUR, FILE_APPEND);
    if (!f) {
        DEBUG_PRINT("[TXLOG] BLAD: nie mozna otworzyc pliku logu");
        return false;
    }
    bool ok = f.write((const uint8_t*)header, hlen) == (size_t)hlen &&
              f.write(_rec, _used) == _used;
    f.flush();
    f.close();
    if (!ok) {
        DEBUG_PRINT("[TXLOG] BLAD: zapis rekordu niepelny (brak miejsca?)");
        return false;
    }

    _lastValid = true;
    _lastEpoch = _curEpoch;
    _lastId = _curId;
    Preferences prefs;
    if (prefs.begin(TXLOG_NVS_NAMESPACE, false)) {
        prefs.putBool("v", true);
        prefs.putUInt("ep", _lastEpoch);
        prefs.putUInt("id", _lastId);
        prefs.end();
    }

    DEBUG_PRINTF("[TXLOG] Zapisano rekord TX epoch=%08X id=%u (%u B)\n",
                 (unsigned)_curEpoch, (unsigned)_curId, (unsigned)_used);
    return true;
}

// ---------------------------------------------------------------- komendy Serial

void TxLog::serviceSerial() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\r' || c == '\n') {
            if (_cmdLen > 0) {
                _cmd[_cmdLen] = '\0';
                handleCommand(_cmd);
                _cmdLen = 0;
            }
        } else if (_cmdLen < sizeof(_cmd) - 1) {
            _cmd[_cmdLen++] = (char)toupper((unsigned char)c);
        }
    }
}

void TxLog::handleCommand(const char* line) {
    if (strncmp(line, "TXLOG", 5) != 0) return;  // inne polecenia ignorujemy
    const char* arg = line + 5;
    while (*arg == ' ') arg++;

    if (*arg == '\0' || strcmp(arg, "INFO") == 0) {
        printInfo();
    } else if (strcmp(arg, "DUMP") == 0) {
        startDump();
    } else if (strcmp(arg, "CLEAR") == 0) {
        clearLogs();
    } else {
        Serial.println("[TXLOG] Komendy: TXLOG | TXLOG DUMP | TXLOG CLEAR");
    }
}

uint32_t TxLog::countRecords(const char* path) {
    if (!LittleFS.exists(path)) return 0;
    File f = LittleFS.open(path, "r");
    if (!f) return 0;
    uint32_t count = 0;
    while (f.available()) {
        String line = f.readStringUntil('\n');
        if (line.startsWith("##### RX ")) count++;
    }
    f.close();
    return count;
}

void TxLog::printInfo() {
    if (!_ok) {
        Serial.println("[TXLOG] LittleFS niedostepny");
        return;
    }
    size_t curSize = 0, oldSize = 0;
    if (LittleFS.exists(TXLOG_FILE_CUR)) { File f = LittleFS.open(TXLOG_FILE_CUR, "r"); if (f) { curSize = f.size(); f.close(); } }
    if (LittleFS.exists(TXLOG_FILE_OLD)) { File f = LittleFS.open(TXLOG_FILE_OLD, "r"); if (f) { oldSize = f.size(); f.close(); } }
    uint32_t records = countRecords(TXLOG_FILE_OLD) + countRecords(TXLOG_FILE_CUR);

    Serial.printf("[TXLOG] rekordow=%u, rozmiar=%u B, ostatni: %s epoch=%08X id=%u, wolne FS=%u B\n",
                  (unsigned)records, (unsigned)(curSize + oldSize),
                  _lastValid ? "tak" : "brak", (unsigned)_lastEpoch, (unsigned)_lastId,
                  (unsigned)(LittleFS.totalBytes() - LittleFS.usedBytes()));
}

void TxLog::clearLogs() {
    if (_dumpStage != 0) finishDump();
    LittleFS.remove(TXLOG_FILE_CUR);
    LittleFS.remove(TXLOG_FILE_OLD);
    Serial.println("[TXLOG] Log skasowany");
}

// ---------------------------------------------------------------- zrzut (nieblokujacy)

bool TxLog::openNextDumpFile() {
    while (_dumpStage < 2) {
        _dumpStage++;
        const char* path = (_dumpStage == 1) ? TXLOG_FILE_OLD : TXLOG_FILE_CUR;
        if (LittleFS.exists(path)) {
            _dumpFile = LittleFS.open(path, "r");
            if (_dumpFile) return true;
        }
    }
    return false;
}

void TxLog::startDump() {
    if (!_ok) {
        Serial.println("[TXLOG] LittleFS niedostepny");
        return;
    }
    if (_dumpStage != 0) return;

    g_serialQuiet = true;
    _dumpBytes = 0;
    Serial.println("===TXLOG-BEGIN===");
    _dumpStage = 0;
    if (!openNextDumpFile()) {
        finishDump();
    }
}

void TxLog::serviceDump() {
    if (_dumpStage == 0 && !_dumpFile) return;

    for (int iter = 0; iter < 16; iter++) {
        int avail = Serial.availableForWrite();
        if (avail < 32) return;  // bufor TX pelny - dokoncz w kolejnym przebiegu loop()

        if (!_dumpFile) {
            if (!openNextDumpFile()) {
                finishDump();
                return;
            }
        }

        uint8_t buf[200];
        size_t want = (size_t)avail < sizeof(buf) ? (size_t)avail : sizeof(buf);
        size_t n = _dumpFile.read(buf, want);
        if (n == 0) {
            _dumpFile.close();
            continue;
        }
        Serial.write(buf, n);
        _dumpBytes += n;
    }
}

void TxLog::finishDump() {
    if (_dumpFile) _dumpFile.close();
    _dumpStage = 0;
    Serial.printf("===TXLOG-END bytes=%u===\n", (unsigned)_dumpBytes);
    g_serialQuiet = false;
}
