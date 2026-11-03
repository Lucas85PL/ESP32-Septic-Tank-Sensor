#ifndef MEAS_PROTOCOL_H
#define MEAS_PROTOCOL_H

// Pakiet pomiaru z historia (TX -> RX), wersja 1 (firmware 2.2.0).
// UWAGA: ten plik jest identyczny w projekcie TX i RX - zmieniaj oba naraz.
//
// TX wysyla razem z biezacym pomiarem do MEAS_HIST_MAX ostatnich ZATWIERDZONYCH pomiarow (najnowszy pierwszy)
// z ich wiekiem w sekundach. Dzieki temu RX nie musi sam zbierac historii: po restarcie, wymianie plytki albo
// utracie pakietow prognoze odtwarza z jednego pakietu.
//
// Rozpoznawanie pakietow po stronie RX: pierwszy bajt MEAS_V2_MAGIC (0xA9) i dlugosc naglowek + count * HistPoint.
// Nie koliduje z: MeasurementPacket (10 B, discovery), AckPacket (2 B), LogChunkPacket (magic 0xA7), LogAckPacket (0xA8).
// AckPacket (potwierdzenie pomiaru) bez zmian - ACK po packetId.

#include <stdint.h>
#include <stddef.h>

#define MEAS_V2_MAGIC     0xA9
#define MEAS_V2_VERSION   1
#define MEAS_HIST_MAX     14      // = HISTORY_SIZE w RX
#define MEAS_FLAG_SYNTHETIC 0x01  // sztuczne 25.0 cm ze strefy martwej (nie wchodzi do regresji w RX)

#pragma pack(push, 1)
struct HistPoint {
    uint16_t distDeci;   // surowa odleglosc [cm * 10]
    uint32_t ageSec;     // wiek punktu wzgledem chwili wyslania pakietu [s]
    uint8_t  flags;      // MEAS_FLAG_*
};

struct MeasurementPacketV2 {
    uint8_t  magic;          // MEAS_V2_MAGIC
    uint8_t  version;        // MEAS_V2_VERSION
    uint8_t  packetId;       // id do ACK (jak w MeasurementPacket); 0 zarezerwowane dla discovery
    uint8_t  validReadings;  // skala 0-10 (jak dotad)
    uint32_t epoch;          // losowy identyfikator "zycia" historii TX (nowy po skasowaniu/uszkodzeniu pliku historii)
    uint32_t seq;            // numer ostatniego zatwierdzonego pomiaru (trwaly, rosnie o 1 na pomiar; punkt i ma numer seq - i)
    uint8_t  count;          // liczba punktow 1..MEAS_HIST_MAX
    HistPoint pts[MEAS_HIST_MAX];   // pts[0] = najnowszy
};
#pragma pack(pop)

#define MEAS_V2_HEADER_SIZE (offsetof(MeasurementPacketV2, pts))
#define MEAS_V2_LEN(count)  (MEAS_V2_HEADER_SIZE + (size_t)(count) * sizeof(HistPoint))

static_assert(sizeof(HistPoint) == 7, "HistPoint musi miec 7 bajtow");
static_assert(MEAS_V2_LEN(MEAS_HIST_MAX) <= 250, "pakiet ESP-NOW max 250 B");

#endif
