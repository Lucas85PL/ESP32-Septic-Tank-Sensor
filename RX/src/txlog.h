#ifndef TXLOG_H
#define TXLOG_H

#include <Arduino.h>
#include <FS.h>
#include "config.h"
#include "log_protocol.h"
#include "espnow_receiver.h"

// Odbior i przechowywanie logow nadajnika (TX) przesylanych przez ESP-NOW + obsluga komend Serial.
//
// Rekord (= jeden cykl TX) jest skladany w RAM z porcji i zapisywany do LittleFS (/txlog.txt) dopiero
// po odebraniu ostatniej porcji; wtedy tez zapamietywany jest (epoch, id) ostatniego kompletnego rekordu
// (NVS), co pozwala odrzucac duplikaty przy ponownej wysylce.
//
// Komendy Serial (115200, zakonczone Enter):
//   TXLOG            - informacje (liczba rekordow, rozmiar, ostatni id)
//   TXLOG DUMP       - zrzut calego logu miedzy znacznikami ===TXLOG-BEGIN=== / ===TXLOG-END bytes=N===
//   TXLOG CLEAR      - kasuje zapisany log (licznik "ostatni id" zostaje - stare rekordy nie wroca)
//   TXLOG HELP
// Wygodny zapis do pliku .txt: tools/txlog_pobierz.py
class TxLog {
public:
    bool begin();
    void loop(EspNowReceiver& rx);   // wolac z loop(): odbior porcji + komendy Serial + zrzut

private:
    bool _ok = false;

    // ostatni kompletny rekord
    bool _lastValid = false;
    uint32_t _lastEpoch = 0;
    uint32_t _lastId = 0;

    // rekord w trakcie skladania
    bool _active = false;
    uint32_t _curEpoch = 0;
    uint32_t _curId = 0;
    uint16_t _curTotal = 0;
    uint16_t _nextSeq = 0;
    size_t _used = 0;
    uint8_t _rec[TXLOG_MAX_RECORD];

    // linia komendy
    char _cmd[48];
    size_t _cmdLen = 0;

    // zrzut
    uint8_t _dumpStage = 0;          // 0 = brak, 1 = txlog.old, 2 = txlog.txt
    File _dumpFile;
    size_t _dumpBytes = 0;

    void handleChunk(EspNowReceiver& rx, const LogChunkSlot& s);
    bool commitRecord();
    void sendAck(EspNowReceiver& rx, const uint8_t* mac, uint32_t epoch, uint32_t id, uint16_t seq, uint8_t status,
                 uint16_t nextSeq);

    void serviceSerial();
    void handleCommand(const char* line);
    void printInfo();
    void clearLogs();
    void startDump();
    void serviceDump();
    void finishDump();
    bool openNextDumpFile();
    uint32_t countRecords(const char* path);
};

extern TxLog txLog;

#endif
