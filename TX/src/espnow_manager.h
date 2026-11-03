#ifndef ESPNOW_MANAGER_H
#define ESPNOW_MANAGER_H

#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include "config.h"
#include "log_protocol.h"
#include "meas_protocol.h"

#pragma pack(push, 1)
struct MeasurementPacket {
    float averageDistance;
    uint8_t validReadings;
    uint32_t timestamp;
    uint8_t packetId;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct AckPacket {
    uint8_t packetId;
    uint8_t status;
};
#pragma pack(pop)

enum class EspNowState {
    DISCOVERING,
    READY,
    SENDING,
    WAITING_ACK,
    SUCCESS,
    FAILED
};

enum class LogChunkResult {
    OK,        // odbiornik potwierdzil porcje
    RESTART,   // odbiornik prosi o nadanie rekordu od poczatku
    REJECT,    // odbiornik odrzucil rekord (pomin)
    TIMEOUT    // brak odpowiedzi
};

class EspNowManager {
public:
    EspNowManager();

    bool begin();
    void shutdown();                    // wylacza ESP-NOW i radio Wi-Fi (np. na czas pomiaru)
    bool discoverReceiver();
    bool sendData(const MeasurementPacket& packet);
    bool sendDataWithRetry(const MeasurementPacket& packet);
    // Pakiet pomiaru z historia (MeasurementPacketV2); len = MEAS_V2_LEN(count). packetId ustawiany tu (jak w sendDataWithRetry).
    bool sendMeasurementWithRetry(MeasurementPacketV2& packet, size_t len);
    LogChunkResult sendLogChunk(const LogChunkPacket& chunk, size_t totalLen, uint16_t* nextSeq = nullptr);
    EspNowState getState() const;
    bool isReceiverKnown() const;
    bool isInitialized() const;
    void printReceiverMAC() const;

private:
    esp_now_peer_info_t _receiverInfo;
    volatile EspNowState _state;
    volatile bool _receiverKnown;
    uint8_t _currentPacketId;
    bool _initialized;
    portMUX_TYPE _mux;
    uint8_t _lastKnownMac[6];

    // potwierdzenie pomiaru
    volatile bool _awaitingAck;
    volatile uint8_t _expectedAckId;
    volatile bool _ackMatched;
    // callback wysylki (poziom MAC)
    volatile bool _sendCbDone;
    volatile bool _sendCbOk;
    // potwierdzenie porcji logu
    volatile bool _logAckReady;
    LogAckPacket _logAck;

    static EspNowManager* _instance;
    static void onDataSent(const uint8_t *mac_addr, esp_now_send_status_t status);
    static void onDataReceived(const uint8_t *mac_addr, const uint8_t *data, int data_len);

    bool sendBuffer(const uint8_t* data, size_t len, uint8_t packetId);   // wspolna wysylka + oczekiwanie na ACK po packetId
    bool addPeer(const uint8_t* mac);
    void printMAC(const uint8_t* mac);
};

#endif
