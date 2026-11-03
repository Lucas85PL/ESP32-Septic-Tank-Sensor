#include "espnow_manager.h"
#include <esp_wifi.h>

EspNowManager* EspNowManager::_instance = nullptr;

EspNowManager::EspNowManager()
    : _state(EspNowState::DISCOVERING)
    , _receiverKnown(false)
    , _currentPacketId(0)
    , _initialized(false)
    , _mux(portMUX_INITIALIZER_UNLOCKED)
    , _awaitingAck(false)
    , _expectedAckId(0)
    , _ackMatched(false)
    , _sendCbDone(false)
    , _sendCbOk(false)
    , _logAckReady(false) {
    _instance = this;
    memset(&_receiverInfo, 0, sizeof(_receiverInfo));
    memset(_lastKnownMac, 0, sizeof(_lastKnownMac));
    memset(&_logAck, 0, sizeof(_logAck));
}

void EspNowManager::onDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
    if (!_instance) return;
    portENTER_CRITICAL(&_instance->_mux);
    _instance->_sendCbOk = (status == ESP_NOW_SEND_SUCCESS);
    _instance->_sendCbDone = true;
    portEXIT_CRITICAL(&_instance->_mux);
}

void EspNowManager::onDataReceived(const uint8_t *mac_addr, const uint8_t *data, int data_len) {
    if (!_instance) return;

    // Potwierdzenie porcji logu (bez wypisywania - porcji jest duzo)
    if (data_len == (int)sizeof(LogAckPacket) && data[0] == LOG_ACK_MAGIC) {
        portENTER_CRITICAL(&_instance->_mux);
        memcpy(&_instance->_logAck, data, sizeof(LogAckPacket));
        _instance->_logAckReady = true;
        portEXIT_CRITICAL(&_instance->_mux);
        return;
    }

    if (data_len == sizeof(AckPacket)) {
        AckPacket* ack = (AckPacket*)data;

        portENTER_CRITICAL(&_instance->_mux);
        if (_instance->_awaitingAck && ack->packetId == _instance->_expectedAckId) {
            _instance->_ackMatched = true;
        }
        portEXIT_CRITICAL(&_instance->_mux);

        DEBUG_PRINTF("[ESP-NOW] Otrzymano ACK dla pakietu %d, status: %d\n",
                    ack->packetId, ack->status);

        if (ack->packetId == 0 && !_instance->_receiverKnown) {
            // TX-4: podczas rediscovery akceptuj tylko poprzednio znany MAC
            static const uint8_t zeroMac[6] = {0, 0, 0, 0, 0, 0};
            bool hasPreviousMac = (memcmp(_instance->_lastKnownMac, zeroMac, 6) != 0);
            if (hasPreviousMac && memcmp(mac_addr, _instance->_lastKnownMac, 6) != 0) {
                DEBUG_PRINT("[ESP-NOW] Rediscovery: odrzucono nieznany MAC");
                return;
            }
            portENTER_CRITICAL(&_instance->_mux);
            memcpy(_instance->_receiverInfo.peer_addr, mac_addr, 6);
            _instance->_receiverKnown = true;
            _instance->_state = EspNowState::READY;
            portEXIT_CRITICAL(&_instance->_mux);
            DEBUG_PRINT("[ESP-NOW] Wykryto odbiornik przez ACK!");
            _instance->printMAC(mac_addr);
        }
    } else {
        DEBUG_PRINT("[ESP-NOW] Otrzymano nieznany pakiet (broadcast od odbiornika)");

        if (!_instance->_receiverKnown) {
            // TX-4: podczas rediscovery akceptuj tylko poprzednio znany MAC
            static const uint8_t zeroMac[6] = {0, 0, 0, 0, 0, 0};
            bool hasPreviousMac = (memcmp(_instance->_lastKnownMac, zeroMac, 6) != 0);
            if (hasPreviousMac && memcmp(mac_addr, _instance->_lastKnownMac, 6) != 0) {
                DEBUG_PRINT("[ESP-NOW] Rediscovery: odrzucono nieznany MAC (broadcast)");
                return;
            }
            portENTER_CRITICAL(&_instance->_mux);
            memcpy(_instance->_receiverInfo.peer_addr, mac_addr, 6);
            _instance->_receiverKnown = true;
            _instance->_state = EspNowState::READY;
            portEXIT_CRITICAL(&_instance->_mux);
            DEBUG_PRINT("[ESP-NOW] Wykryto odbiornik!");
            _instance->printMAC(mac_addr);
        }
    }
}

bool EspNowManager::begin() {
    DEBUG_PRINT("[ESP-NOW] Inicjalizacja...");

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

    if (esp_now_init() != ESP_OK) {
        DEBUG_PRINT("[ESP-NOW] Błąd inicjalizacji!");
        return false;
    }

    esp_now_register_send_cb(onDataSent);
    esp_now_register_recv_cb(onDataReceived);

    DEBUG_PRINT("[ESP-NOW] Zainicjalizowany pomyślnie");
    DEBUG_PRINTF("[ESP-NOW] Mój MAC: %s\n", WiFi.macAddress().c_str());

    _initialized = true;
    return true;
}

// Wylacza ESP-NOW i radio (pomiar odbywa sie bez Wi-Fi). Zapamietuje MAC odbiornika dla filtra rediscovery.
void EspNowManager::shutdown() {
    if (_receiverKnown) {
        memcpy(_lastKnownMac, _receiverInfo.peer_addr, 6);
    }
    if (_initialized) {
        esp_now_deinit();
    }
    WiFi.mode(WIFI_OFF);
    _initialized = false;
    _receiverKnown = false;
    _state = EspNowState::DISCOVERING;
    DEBUG_PRINT("[ESP-NOW] Radio wylaczone");
}

bool EspNowManager::isInitialized() const {
    return _initialized;
}

void EspNowManager::printMAC(const uint8_t* mac) {
    DEBUG_PRINTF("[ESP-NOW] MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

void EspNowManager::printReceiverMAC() const {
    if (_receiverKnown) {
        DEBUG_PRINTF("[ESP-NOW] MAC odbiornika: %02X:%02X:%02X:%02X:%02X:%02X\n",
                    _receiverInfo.peer_addr[0], _receiverInfo.peer_addr[1],
                    _receiverInfo.peer_addr[2], _receiverInfo.peer_addr[3],
                    _receiverInfo.peer_addr[4], _receiverInfo.peer_addr[5]);
    } else {
        DEBUG_PRINT("[ESP-NOW] Odbiornik nieznany");
    }
}

bool EspNowManager::isReceiverKnown() const {
    return _receiverKnown;
}

EspNowState EspNowManager::getState() const {
    return _state;
}

bool EspNowManager::addPeer(const uint8_t* mac) {
    uint8_t macCopy[6];
    memcpy(macCopy, mac, 6);

    if (esp_now_is_peer_exist(macCopy)) {
        esp_now_del_peer(macCopy);
    }

    memset(&_receiverInfo, 0, sizeof(_receiverInfo));
    memcpy(_receiverInfo.peer_addr, macCopy, 6);
    _receiverInfo.channel = ESPNOW_CHANNEL;
    _receiverInfo.encrypt = false;

    if (esp_now_add_peer(&_receiverInfo) != ESP_OK) {
        DEBUG_PRINT("[ESP-NOW] Błąd dodawania peera");
        return false;
    }

    return true;
}

bool EspNowManager::discoverReceiver() {
    if (!_initialized) {
        DEBUG_PRINT("[ESP-NOW] Brak inicjalizacji - nie mozna szukac odbiornika");
        return false;
    }

    // TX-4: zapisz poprzedni MAC przed resetem (filtr podczas rediscovery)
    if (_receiverKnown) {
        memcpy(_lastKnownMac, _receiverInfo.peer_addr, 6);
    }
    // FIX #2: reset stanu przed każdym wyszukiwaniem (także przy rediscovery)
    _receiverKnown = false;
    _state = EspNowState::DISCOVERING;

    DEBUG_PRINT("[ESP-NOW] Szukam odbiornika...");
    DEBUG_PRINT("[ESP-NOW] Upewnij się, że odbiornik jest włączony i nadaje");

    uint8_t broadcastMac[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

    if (!addPeer(broadcastMac)) {
        DEBUG_PRINT("[ESP-NOW] Nie można dodać adresu broadcast");
        return false;
    }

    MeasurementPacket discoveryPacket = {};
    discoveryPacket.timestamp = millis();

    unsigned long startTime = millis();

    while (!_receiverKnown &&
           (millis() - startTime) < ESPNOW_RECEIVER_DISCOVERY_TIMEOUT_MS) {

        esp_now_send(broadcastMac, (uint8_t*)&discoveryPacket, sizeof(discoveryPacket));

        for (int i = 0; i < 50 && !_receiverKnown; i++) {
            delay(100);
        }

        if (!_receiverKnown) {
            DEBUG_PRINTF("[ESP-NOW] Czekam na odbiornik... (%.1fs)\n",
                        (millis() - startTime) / 1000.0f);
        }
    }

    if (_receiverKnown) {
        esp_now_del_peer(broadcastMac);

        if (!addPeer(_receiverInfo.peer_addr)) {
            DEBUG_PRINT("[ESP-NOW] Błąd dodawania odbiornika jako peera");
            return false;
        }

        DEBUG_PRINT("[ESP-NOW] Odbiornik wykryty i dodany!");
        printReceiverMAC();
        _state = EspNowState::READY;
        return true;
    }

    DEBUG_PRINT("[ESP-NOW] Nie wykryto odbiornika w limicie czasu");
    return false;
}

bool EspNowManager::sendData(const MeasurementPacket& packet) {
    return sendBuffer((const uint8_t*)&packet, sizeof(packet), packet.packetId);
}

bool EspNowManager::sendBuffer(const uint8_t* data, size_t len, uint8_t packetId) {
    if (!_receiverKnown) {
        DEBUG_PRINT("[ESP-NOW] Brak znanego odbiornika");
        return false;
    }

    portENTER_CRITICAL(&_mux);
    _ackMatched = false;
    _sendCbDone = false;
    _sendCbOk = false;
    _expectedAckId = packetId;
    _awaitingAck = true;
    portEXIT_CRITICAL(&_mux);
    _state = EspNowState::SENDING;

    DEBUG_PRINT("[ESP-NOW] Wysyłanie danych...");
    DEBUG_PRINTF("[ESP-NOW] Pakiet ID: %d, %u B\n", packetId, (unsigned)len);

    esp_err_t result = esp_now_send(_receiverInfo.peer_addr, data, len);

    if (result != ESP_OK) {
        DEBUG_PRINT("[ESP-NOW] Błąd wysyłania!");
        _awaitingAck = false;
        _state = EspNowState::FAILED;
        return false;
    }

    // Sukces = ACK aplikacyjny z pasujacym packetId (kolejnosc wzgledem callbacku wysylki nie ma znaczenia).
    // Gdy warstwa MAC zglosi brak potwierdzenia, czekamy jeszcze krotko na ewentualny ACK aplikacyjny.
    const unsigned long startTime = millis();
    unsigned long failSeen = 0;
    bool matched = false;
    while ((millis() - startTime) < ESPNOW_ACK_TIMEOUT_MS) {
        bool cbDone, cbOk;
        portENTER_CRITICAL(&_mux);
        matched = _ackMatched;
        cbDone = _sendCbDone;
        cbOk = _sendCbOk;
        portEXIT_CRITICAL(&_mux);

        if (matched) break;
        if (cbDone && !cbOk) {
            if (failSeen == 0) failSeen = millis();
            if (millis() - failSeen > 150) break;
        }
        delay(5);
    }

    portENTER_CRITICAL(&_mux);
    _awaitingAck = false;
    portEXIT_CRITICAL(&_mux);

    if (matched) {
        _state = EspNowState::SUCCESS;
        DEBUG_PRINT("[ESP-NOW] Potwierdzenie otrzymane!");
        return true;
    }

    DEBUG_PRINT("[ESP-NOW] Brak potwierdzenia");
    _state = EspNowState::FAILED;
    return false;
}

bool EspNowManager::sendDataWithRetry(const MeasurementPacket& packet) {
    MeasurementPacket retryPacket = packet;

    for (int attempt = 1; attempt <= ESPNOW_MAX_RETRIES; attempt++) {
        retryPacket.packetId = ++_currentPacketId;

        DEBUG_PRINTF("[ESP-NOW] Próba %d/%d\n", attempt, ESPNOW_MAX_RETRIES);

        if (sendData(retryPacket)) {
            return true;
        }

        if (attempt < ESPNOW_MAX_RETRIES) {
            DEBUG_PRINTF("[ESP-NOW] Ponowna próba za %d ms...\n", ESPNOW_RETRY_DELAY_MS);
            delay(ESPNOW_RETRY_DELAY_MS);
        }
    }

    DEBUG_PRINT("[ESP-NOW] Wszystkie próby nieudane");
    return false;
}

bool EspNowManager::sendMeasurementWithRetry(MeasurementPacketV2& packet, size_t len) {
    for (int attempt = 1; attempt <= ESPNOW_MAX_RETRIES; attempt++) {
        packet.packetId = ++_currentPacketId;

        DEBUG_PRINTF("[ESP-NOW] Próba %d/%d (pomiar z historia, seq %lu, %u pkt)\n", attempt, ESPNOW_MAX_RETRIES,
                     (unsigned long)packet.seq, (unsigned)packet.count);

        if (sendBuffer((const uint8_t*)&packet, len, packet.packetId)) {
            return true;
        }

        if (attempt < ESPNOW_MAX_RETRIES) {
            DEBUG_PRINTF("[ESP-NOW] Ponowna próba za %d ms...\n", ESPNOW_RETRY_DELAY_MS);
            delay(ESPNOW_RETRY_DELAY_MS);
        }
    }

    DEBUG_PRINT("[ESP-NOW] Wszystkie próby nieudane");
    return false;
}

// Wysyla jedna porcje logu i czeka na LogAck z pasujacym (epoch, cycleId, seq). Do LOG_CHUNK_RETRIES prob.
LogChunkResult EspNowManager::sendLogChunk(const LogChunkPacket& chunk, size_t totalLen, uint16_t* nextSeq) {
    if (!_receiverKnown) return LogChunkResult::TIMEOUT;

    for (int attempt = 0; attempt < LOG_CHUNK_RETRIES; attempt++) {
        portENTER_CRITICAL(&_mux);
        _logAckReady = false;
        portEXIT_CRITICAL(&_mux);

        if (esp_now_send(_receiverInfo.peer_addr, (const uint8_t*)&chunk, totalLen) != ESP_OK) {
            delay(20);
            continue;
        }

        const unsigned long t0 = millis();
        while ((millis() - t0) < LOG_CHUNK_ACK_TIMEOUT_MS) {
            if (_logAckReady) {
                LogAckPacket ack;
                portENTER_CRITICAL(&_mux);
                memcpy(&ack, &_logAck, sizeof(ack));
                _logAckReady = false;
                portEXIT_CRITICAL(&_mux);

                if (ack.epoch == chunk.epoch && ack.cycleId == chunk.cycleId && ack.seq == chunk.seq) {
                    if (nextSeq) *nextSeq = ack.nextSeq;
                    if (ack.status == LOG_ACK_RESTART) return LogChunkResult::RESTART;
                    if (ack.status == LOG_ACK_REJECT) return LogChunkResult::REJECT;
                    return LogChunkResult::OK;
                }
                // spozniony ACK innej porcji - czekaj dalej
            }
            delay(1);
        }
    }
    return LogChunkResult::TIMEOUT;
}
