#ifndef HISTORY_SYNC_H
#define HISTORY_SYNC_H

#include <Arduino.h>
#include "config.h"
#include "display.h"
#include "espnow_receiver.h"
#include "storage.h"
#include "meas_protocol.h"

// Obsluga historii pomiarow odebranej w pakiecie TX (MeasurementPacketV2):
//  - odrzucanie pakietow nieaktualnych (seq starszy niz juz odebrany) i sprzed RESET przyciskiem (odciecie: epoka + seq),
//  - przycinanie historii: punkty z seq <= odciecie nie wchodza do prognozy; skok odleglosci w gore > EMPTY_THRESHOLD
//    w historii (wywoz) odcina starsze punkty,
//  - blob historii do zapisu w NVS (po utracie zasilania RX prognoza wraca od razu).
class HistorySync {
public:
    HistorySync();

    // Po utracie zasilania: wczytaj odciecie po RESET i ostatnio zapisana historie (epoka/seq)
    void begin(Storage& storage);
    // true = pakiet do pokazania; out/n = punkty (najnowszy pierwszy). false = pakiet pominac.
    bool process(const ReceivedData& d, HistPointIn* out, uint8_t& n);
    // Historia ostatniego przyjetego pakietu w formacie do zapisu w NVS
    const HistBlob& blob() const { return _blob; }
    // Punkty z blobu wczytanego w begin() (do odtworzenia prognozy po restarcie); zwraca liczbe punktow
    uint8_t restorePoints(HistPointIn* out) const;
    // Wolac PO storage.clear() przy RESET przyciskiem: zapamietuje (epoka, seq) ostatniego pakietu jako odciecie
    void onManualReset(Storage& storage);

private:
    bool _lastKnown;
    uint32_t _lastEpoch;
    uint32_t _lastSeq;
    bool _cutValid;
    uint32_t _cutEpoch;
    uint32_t _cutSeq;
    HistBlob _blob;
    bool _blobValid;
};

#endif
