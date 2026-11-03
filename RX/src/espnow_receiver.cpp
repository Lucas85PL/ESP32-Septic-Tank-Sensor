#include "espnow_receiver.h"
#include <esp_wifi.h>

EspNowReceiver* EspNowReceiver::_instance = nullptr;

EspNowReceiver::EspNowReceiver()
    : _senderKnown(false)
    , _totalPackets(0)
    , _lastReceiveTime(0)
    , _hasNewData(false)
    , _pendingSend(false)
    , _pendingPacketId(0)
    , _logSlotFull(false)
    , _rxQueue(nullptr) {
    _instance = this;
    memset(_senderMac, 0, sizeof(_senderMac));
    memset(&_receivedData, 0, sizeof(_receivedData));
    _receivedData.hasNewData = false;
    _receivedData.senderKnown = false;
    memset(_receivedData.senderMac, 0, sizeof(_receivedData.senderMac));
    _receivedData.totalPackets = 0;
    _receivedData.lastReceiveTime = 0;
}

bool EspNowReceiver::begin() {
    DEBUG_PRINT("[ESP-NOW] Inicjalizacja odbiornika...");
    
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    
    DEBUG_PRINTF("[ESP-NOW] Moj MAC: %s\n", WiFi.macAddress().c_str());
    
    if (esp_now_init() != ESP_OK) {
        DEBUG_PRINT("[ESP-NOW] Blad inicjalizacji!");
        return false;
    }
    
    _rxQueue = xQueueCreate(8, sizeof(RxEvent));
    if (!_rxQueue) {
        DEBUG_PRINT("[ESP-NOW] Blad tworzenia kolejki!");
        return false;
    }

    esp_now_register_recv_cb(onDataReceived);
    
    DEBUG_PRINT("[ESP-NOW] Odbiornik gotowy, nasluchuje...");
    
    return true;
}

// Callback (zadanie Wi-Fi): tylko kopiuje pakiet do kolejki - zadnej obrobki, wypisywania ani operacji na plikach.
void EspNowReceiver::onDataReceived(const uint8_t *mac_addr, const uint8_t *data, int data_len) {
    if (!_instance || !_instance->_rxQueue || data_len <= 0 || data_len > (int)sizeof(RxEvent::data)) {
        return;
    }
    RxEvent ev;
    memcpy(ev.mac, mac_addr, 6);
    ev.len = (uint16_t)data_len;
    memcpy(ev.data, data, data_len);
    xQueueSend(_instance->_rxQueue, &ev, 0);   // kolejka pelna = pakiet gubiony (nadajnik ponowi)
}

void EspNowReceiver::poll() {
    if (!_rxQueue) return;
    RxEvent ev;
    while (xQueueReceive(_rxQueue, &ev, 0) == pdTRUE) {
        processPacket(ev.mac, ev.data, ev.len);
        sendPendingResponse();   // ACK od razu (przed rysowaniem ekranu)
    }
}

void EspNowReceiver::processPacket(const uint8_t *mac_addr, const uint8_t *data, int data_len) {
    if (data_len >= (int)(MEAS_V2_HEADER_SIZE + sizeof(HistPoint)) && data[0] == MEAS_V2_MAGIC) {
        // pomiar z historia zatwierdzonych pomiarow TX (firmware >= 2.2.0)
        MeasurementPacketV2 pkt;
        memset(&pkt, 0, sizeof(pkt));
        memcpy(&pkt, data, data_len < (int)sizeof(pkt) ? data_len : (int)sizeof(pkt));
        if (pkt.version != MEAS_V2_VERSION || pkt.count < 1 || pkt.count > MEAS_HIST_MAX ||
            data_len != (int)MEAS_V2_LEN(pkt.count)) {
            DEBUG_PRINTF("[ESP-NOW] Odrzucono pakiet pomiaru: wersja %d, punktow %d, rozmiar %d\n",
                         pkt.version, pkt.count, data_len);
            return;
        }

        DEBUG_PRINTF("[ESP-NOW] Pakiet ID: %d, seq %lu, punktow %d, najnowszy %.1f cm (wiek %lu s)\n",
                     pkt.packetId, (unsigned long)pkt.seq, pkt.count, pkt.pts[0].distDeci / 10.0f,
                     (unsigned long)pkt.pts[0].ageSec);

        if (!_senderKnown) {
            memcpy(_senderMac, mac_addr, 6);
            _senderKnown = true;
            DEBUG_PRINT("[ESP-NOW] Zapamietano nadajnik:");
            printMacAddress(_senderMac);
        }

        _totalPackets++;
        _lastReceiveTime = millis();

        _receivedData.distanceCm = pkt.pts[0].distDeci / 10.0f;
        _receivedData.validReadings = pkt.validReadings;
        _receivedData.timestamp = 0;
        _receivedData.packetId = pkt.packetId;
        _receivedData.hasHistory = true;
        _receivedData.histEpoch = pkt.epoch;
        _receivedData.histSeq = pkt.seq;
        _receivedData.histCount = pkt.count;
        memcpy(_receivedData.hist, pkt.pts, sizeof(_receivedData.hist));
        _receivedData.hasNewData = true;
        _hasNewData = true;
        _receivedData.totalPackets = _totalPackets;
        _receivedData.senderKnown = _senderKnown;
        _receivedData.lastReceiveTime = _lastReceiveTime;
        memcpy(_receivedData.senderMac, mac_addr, 6);

        memcpy(_pendingMac, mac_addr, 6);
        _pendingPacketId = pkt.packetId;
        _pendingSend = true;
        return;
    }

    if (data_len == sizeof(MeasurementPacket)) {
        MeasurementPacket* packet = (MeasurementPacket*)data;
        
        DEBUG_PRINTF("[ESP-NOW] Otrzymano pakiet ID: %d\n", packet->packetId);
        DEBUG_PRINTF("[ESP-NOW] Odleglosc: %.2f cm\n", packet->averageDistance);
        DEBUG_PRINTF("[ESP-NOW] Pomiarow: %d\n", packet->validReadings);
        
        if (packet->packetId == 0 && packet->averageDistance == 0) {
            DEBUG_PRINT("[ESP-NOW] Wykryto pakiet DISCOVERY");
            memcpy(_pendingMac, mac_addr, 6);
            _pendingPacketId = 0;
            _pendingSend = true;
            return;
        }
        
        if (!_senderKnown) {
            memcpy(_senderMac, mac_addr, 6);
            _senderKnown = true;
            DEBUG_PRINT("[ESP-NOW] Zapamietano nadajnik:");
            printMacAddress(_senderMac);
        }
        
        _totalPackets++;
        _lastReceiveTime = millis();
        
        _receivedData.distanceCm = packet->averageDistance;
        _receivedData.validReadings = packet->validReadings;
        _receivedData.timestamp = packet->timestamp;
        _receivedData.packetId = packet->packetId;
        _receivedData.hasHistory = false;   // pakiet w starym formacie (bez historii)
        _receivedData.hasNewData = true;
        _hasNewData = true;  // volatile flaga dla pollingu w loop()
        _receivedData.totalPackets = _totalPackets;
        _receivedData.senderKnown = _senderKnown;
        _receivedData.lastReceiveTime = _lastReceiveTime;
        memcpy(_receivedData.senderMac, mac_addr, 6);
        
        memcpy(_pendingMac, mac_addr, 6);
        _pendingPacketId = packet->packetId;
        _pendingSend = true;

    } else if (data_len > LOG_CHUNK_HEADER_SIZE && data_len <= (int)sizeof(LogChunkPacket) &&
               data[0] == LOG_CHUNK_MAGIC) {
        // porcja logu TX: tylko skopiuj (slot jedyny - nadajnik pracuje stop-and-wait, a przy zajetym slocie ponowi)
        if (!_logSlotFull) {
            memcpy(_logSlot.mac, mac_addr, 6);
            _logSlot.len = (uint16_t)data_len;
            memcpy(_logSlot.data, data, data_len);
            _logSlotFull = true;
        }
    } else {
        DEBUG_PRINTF("[ESP-NOW] Nieznany pakiet, rozmiar: %d\n", data_len);
    }
}

bool EspNowReceiver::takeLogChunk(LogChunkSlot& out) {
    if (!_logSlotFull) return false;
    out = _logSlot;
    _logSlotFull = false;
    return true;
}

bool EspNowReceiver::sendLogAck(const uint8_t* mac, const LogAckPacket& ack) {
    if (!esp_now_is_peer_exist(mac)) {
        esp_now_peer_info_t peerInfo;
        memset(&peerInfo, 0, sizeof(peerInfo));
        memcpy(peerInfo.peer_addr, mac, 6);
        peerInfo.channel = ESPNOW_CHANNEL;
        peerInfo.encrypt = false;
        if (esp_now_add_peer(&peerInfo) != ESP_OK) {
            return false;
        }
    }
    return esp_now_send(mac, (const uint8_t*)&ack, sizeof(ack)) == ESP_OK;
}

bool EspNowReceiver::sendAck(const uint8_t* mac, uint8_t packetId) {
    if (!esp_now_is_peer_exist(mac)) {
        esp_now_peer_info_t peerInfo;
        memset(&peerInfo, 0, sizeof(peerInfo));
        memcpy(peerInfo.peer_addr, mac, 6);
        peerInfo.channel = ESPNOW_CHANNEL;
        peerInfo.encrypt = false;
        
        if (esp_now_add_peer(&peerInfo) != ESP_OK) {
            DEBUG_PRINT("[ESP-NOW] Nie mozna dodac nadajnika jako peera");
            return false;
        }
    }
    
    AckPacket ack;
    ack.packetId = packetId;
    ack.status = 1;
    
    esp_err_t result = esp_now_send(mac, (uint8_t*)&ack, sizeof(ack));
    
    if (result == ESP_OK) {
        DEBUG_PRINTF("[ESP-NOW] Wyslano ACK dla pakietu %d\n", packetId);
        return true;
    } else {
        DEBUG_PRINT("[ESP-NOW] Blad wysylania ACK");
        return false;
    }
}

void EspNowReceiver::sendDiscoveryResponse(const uint8_t* mac) {
    if (!esp_now_is_peer_exist(mac)) {
        esp_now_peer_info_t peerInfo;
        memset(&peerInfo, 0, sizeof(peerInfo));
        memcpy(peerInfo.peer_addr, mac, 6);
        peerInfo.channel = ESPNOW_CHANNEL;
        peerInfo.encrypt = false;
        
        if (esp_now_add_peer(&peerInfo) != ESP_OK) {
            DEBUG_PRINT("[ESP-NOW] Nie mozna dodac nadajnika dla discovery response");
            return;
        }
    }
    
    AckPacket response;
    response.packetId = 0;
    response.status = 1;
    
    esp_err_t result = esp_now_send(mac, (uint8_t*)&response, sizeof(response));
    
    if (result == ESP_OK) {
        DEBUG_PRINT("[ESP-NOW] Wyslano odpowiedz DISCOVERY");
    } else {
        DEBUG_PRINT("[ESP-NOW] Blad wysylania odpowiedzi DISCOVERY");
    }
}

void EspNowReceiver::sendPendingResponse() {
    if (!_pendingSend) return;
    _pendingSend = false;
    sendAck(_pendingMac, _pendingPacketId);
}

ReceivedData EspNowReceiver::getData() {
    return _receivedData;
}

void EspNowReceiver::clearNewDataFlag() {
    _hasNewData = false;
    _receivedData.hasNewData = false;
}

bool EspNowReceiver::hasNewData() const {
    return _hasNewData;
}

void EspNowReceiver::printMAC() const {
    DEBUG_PRINTF("[ESP-NOW] MAC odbiornika: %s\n", WiFi.macAddress().c_str());
}

void EspNowReceiver::printMacAddress(const uint8_t* mac) {
    DEBUG_PRINTF("[ESP-NOW] MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

uint16_t EspNowReceiver::getTotalPackets() const {
    return _totalPackets;
}

bool EspNowReceiver::isSenderKnown() const {
    return _senderKnown;
}

void EspNowReceiver::getSenderMac(uint8_t* mac) const {
    memcpy(mac, _senderMac, 6);
}

void EspNowReceiver::getReceiverMac(uint8_t* mac) const {
    String macStr = WiFi.macAddress();
    sscanf(macStr.c_str(), "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
           &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]);
}

uint32_t EspNowReceiver::getLastReceiveTime() const {
    return _lastReceiveTime;
}
