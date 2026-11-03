#include "history_sync.h"
#include <string.h>

HistorySync::HistorySync()
    : _lastKnown(false), _lastEpoch(0), _lastSeq(0)
    , _cutValid(false), _cutEpoch(0), _cutSeq(0)
    , _blobValid(false) {
    memset(&_blob, 0, sizeof(_blob));
}

void HistorySync::begin(Storage& storage) {
    _cutValid = storage.loadCut(_cutEpoch, _cutSeq);
    if (_cutValid) {
        DEBUG_PRINTF("[HIST] Odciecie po RESET: epoka %08lX, seq <= %lu\n", (unsigned long)_cutEpoch, (unsigned long)_cutSeq);
    }
    _blobValid = storage.loadHistory(_blob);
    if (_blobValid) {
        _lastKnown = true;
        _lastEpoch = _blob.epoch;
        _lastSeq = _blob.seq;
        DEBUG_PRINTF("[HIST] Historia z NVS: %u pkt, epoka %08lX, seq %lu\n", (unsigned)_blob.count,
                     (unsigned long)_blob.epoch, (unsigned long)_blob.seq);
    }
}

bool HistorySync::process(const ReceivedData& d, HistPointIn* out, uint8_t& n) {
    n = 0;
    if (!d.hasHistory || d.histCount < 1 || d.histCount > MEAS_HIST_MAX) return false;

    const uint32_t epoch = d.histEpoch;
    const uint32_t seq = d.histSeq;

    // pakiet sprzed RESET przyciskiem (TX jeszcze nie wyczyscil historii) - ignoruj
    if (_cutValid && _cutEpoch == epoch && seq <= _cutSeq) {
        DEBUG_PRINTF("[HIST] Pakiet seq %lu sprzed RESET (odciecie %lu) - pomijam\n", (unsigned long)seq, (unsigned long)_cutSeq);
        return false;
    }
    // opozniony / stary pakiet tej samej epoki (rowny seq = powtorka po utraconym ACK - przyjmujemy)
    if (_lastKnown && _lastEpoch == epoch && seq < _lastSeq) {
        DEBUG_PRINTF("[HIST] Pakiet seq %lu starszy niz odebrany %lu - pomijam\n", (unsigned long)seq, (unsigned long)_lastSeq);
        return false;
    }

    uint8_t keep = d.histCount;
    if (_cutValid) {
        if (_cutEpoch == epoch) {
            // punkt i ma numer seq - i: zostaja tylko punkty nowsze niz odciecie
            const uint32_t allowed = seq - _cutSeq;
            if (allowed < keep) keep = (uint8_t)allowed;
        } else {
            _cutValid = false;   // nowa epoka TX (po skasowaniu historii) - odciecie nieaktualne
        }
    }

    // Skok odleglosci w gore (wywoz) w odebranej historii: tylko punkty nowsze niz skok
    for (uint8_t j = 0; j + 1 < keep; j++) {
        const int32_t rise = (int32_t)d.hist[j].distDeci - (int32_t)d.hist[j + 1].distDeci;
        if (rise > (int32_t)EMPTY_THRESHOLD * 10) {
            keep = j + 1;
            break;
        }
    }
    if (keep == 0) return false;

    _blob.epoch = epoch;
    _blob.seq = seq;
    _blob.count = keep;
    for (uint8_t i = 0; i < keep; i++) {
        _blob.pts[i] = d.hist[i];
        out[i].rawCm = d.hist[i].distDeci / 10.0f;
        out[i].ageSec = d.hist[i].ageSec;
        out[i].synthetic = (d.hist[i].flags & MEAS_FLAG_SYNTHETIC) != 0;
    }
    n = keep;
    _blobValid = true;
    _lastKnown = true;
    _lastEpoch = epoch;
    _lastSeq = seq;
    return true;
}

uint8_t HistorySync::restorePoints(HistPointIn* out) const {
    if (!_blobValid || _blob.count < 1 || _blob.count > MEAS_HIST_MAX) return 0;
    for (uint8_t i = 0; i < _blob.count; i++) {
        out[i].rawCm = _blob.pts[i].distDeci / 10.0f;
        out[i].ageSec = _blob.pts[i].ageSec;
        out[i].synthetic = (_blob.pts[i].flags & MEAS_FLAG_SYNTHETIC) != 0;
    }
    return _blob.count;
}

void HistorySync::onManualReset(Storage& storage) {
    if (_lastKnown) {
        _cutValid = true;
        _cutEpoch = _lastEpoch;
        _cutSeq = _lastSeq;
    }
    _lastKnown = false;
    _blobValid = false;
    memset(&_blob, 0, sizeof(_blob));
    if (_cutValid) {
        storage.saveCut(_cutEpoch, _cutSeq);   // storage.clear() skasowal wszystko - odciecie zapisujemy ponownie
        DEBUG_PRINTF("[HIST] RESET: odciecie epoka %08lX, seq <= %lu\n", (unsigned long)_cutEpoch, (unsigned long)_cutSeq);
    }
}
