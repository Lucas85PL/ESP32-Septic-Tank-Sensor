#ifndef LOG_PROTOCOL_H
#define LOG_PROTOCOL_H

// Protokol przesylania logow TX -> RX przez ESP-NOW (stop-and-wait, kazda porcja potwierdzana).
// UWAGA: ten plik jest identyczny w projekcie TX i RX - zmieniaj oba naraz.
//
// Rozmiary pakietow nie koliduja z istniejacymi: MeasurementPacket = 10 B, AckPacket = 2 B,
// LogAckPacket = 14 B, LogChunkPacket >= 15 B. Dodatkowo pierwszy bajt to magic.

#include <stdint.h>

#define LOG_CHUNK_MAGIC     0xA7
#define LOG_ACK_MAGIC       0xA8
#define LOG_CHUNK_DATA_MAX  224
#define LOG_CHUNK_HEADER_SIZE 14

// status w LogAckPacket
#define LOG_ACK_OK       0   // porcja przyjeta (lub duplikat)
#define LOG_ACK_RESTART  1   // niezgodna kolejnosc - nadaj rekord od porcji 0
#define LOG_ACK_REJECT   2   // rekord nie do przyjecia (np. za duzy) - pomin

#pragma pack(push, 1)
struct LogChunkPacket {
    uint8_t  magic;      // LOG_CHUNK_MAGIC
    uint32_t epoch;      // losowy identyfikator "zycia" logu nadajnika (zmienia sie po skasowaniu flash)
    uint32_t cycleId;    // trwaly numer cyklu (rosnie monotonicznie w obrebie epoch)
    uint16_t seq;        // numer porcji (od 0)
    uint16_t total;      // liczba porcji w rekordzie
    uint8_t  len;        // bajtow danych w tej porcji
    uint8_t  data[LOG_CHUNK_DATA_MAX];
};

struct LogAckPacket {
    uint8_t  magic;      // LOG_ACK_MAGIC
    uint32_t epoch;
    uint32_t cycleId;
    uint16_t seq;
    uint8_t  status;     // LOG_ACK_*
    uint16_t nextSeq;    // numer porcji, ktorej odbiornik oczekuje w biezacym rekordzie (0 = zacznij od poczatku;
                         // przy statusie OK = nastepna oczekiwana). Pozwala wznowic przerwany rekord bez nadawania od zera.
};
#pragma pack(pop)

#endif
