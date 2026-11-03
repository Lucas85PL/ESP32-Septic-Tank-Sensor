#ifndef ESPNOW_RECEIVER_H
#define ESPNOW_RECEIVER_H

#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
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

struct ReceivedData {
    float distanceCm;
    uint8_t validReadings;
    uint32_t timestamp;
    uint8_t packetId;
    bool hasNewData;
    uint16_t totalPackets;
    bool senderKnown;
    uint8_t senderMac[6];
    uint32_t lastReceiveTime;
    // pakiet z historia (MeasurementPacketV2); hist[0] = najnowszy pomiar (= distanceCm)
    bool hasHistory;
    uint32_t histEpoch;
    uint32_t histSeq;
    uint8_t histCount;
    HistPoint hist[MEAS_HIST_MAX];
};

// Porcja logu TX skopiowana z callbacku ESP-NOW; przetwarzana w loop() (zadnych operacji na plikach w callbacku)
struct LogChunkSlot {
    uint8_t mac[6];
    uint16_t len;
    uint8_t data[250];
};

// Pakiet skopiowany z callbacku ESP-NOW do kolejki; cala obrobka odbywa sie w loop() (jeden watek - bez wyscigow)
struct RxEvent {
    uint8_t mac[6];
    uint16_t len;
    uint8_t data[250];
};

class EspNowReceiver {
public:
    EspNowReceiver();
    
    bool begin();
    void poll();   // wolac z loop() na poczatku: przetwarza pakiety z kolejki i wysyla ACK
    ReceivedData getData();
    void clearNewDataFlag();
    bool hasNewData() const;
    void sendPendingResponse();
    void printMAC() const;
    
    uint16_t getTotalPackets() const;
    bool isSenderKnown() const;
    void getSenderMac(uint8_t* mac) const;
    void getReceiverMac(uint8_t* mac) const;
    uint32_t getLastReceiveTime() const;

    // logi TX -> RX
    bool takeLogChunk(LogChunkSlot& out);                       // true, gdy odebrano porcje (kopiuje i zwalnia slot)
    bool sendLogAck(const uint8_t* mac, const LogAckPacket& ack);
    
private:
    ReceivedData _receivedData;
    uint8_t _senderMac[6];
    volatile bool _senderKnown;
    volatile uint16_t _totalPackets;
    volatile uint32_t _lastReceiveTime;
    volatile bool _hasNewData;  // osobna flaga volatile — pisana w callbacku, czytana w loop
    volatile bool _pendingSend;
    uint8_t _pendingMac[6];
    volatile uint8_t _pendingPacketId;
    LogChunkSlot _logSlot;
    volatile bool _logSlotFull;
    QueueHandle_t _rxQueue;
    
    static EspNowReceiver* _instance;
    static void onDataReceived(const uint8_t *mac_addr, const uint8_t *data, int data_len);
    
    void processPacket(const uint8_t *mac_addr, const uint8_t *data, int data_len);
    bool sendAck(const uint8_t* mac, uint8_t packetId);
    void sendDiscoveryResponse(const uint8_t* mac);
    void printMacAddress(const uint8_t* mac);
};

#endif
