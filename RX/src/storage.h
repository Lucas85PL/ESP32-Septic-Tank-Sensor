#ifndef STORAGE_H
#define STORAGE_H

#include <Arduino.h>
#include <Preferences.h>
#include "config.h"
#include "meas_protocol.h"

// Historia z ostatniego pakietu TX (punkty z wiekiem wzgledem chwili odbioru) - po utracie zasilania RX prognoza wraca od razu
struct HistBlob {
    uint32_t epoch;
    uint32_t seq;
    uint8_t count;
    HistPoint pts[MEAS_HIST_MAX];   // najnowszy pierwszy
};

// Trwały zapis ostatniego poprawnego pomiaru (NVS) - przetrwa utratę zasilania.
// Brak zegara RTC: zapisujemy wiek pomiaru w chwili zapisu; czas bez zasilania nie jest liczony.
class Storage {
public:
    void saveSnapshot(float rawDistanceCm, uint32_t ageSeconds);
    bool load(float& rawDistanceCm, uint32_t& ageSeconds);
    void clear();   // kasuje WSZYSTKO (w tym odciecie po RESET - patrz HistorySync::onManualReset, ktory zapisuje je ponownie)

    void saveHistory(const HistBlob& blob);
    bool loadHistory(HistBlob& blob);
    // Odciecie po RESET przyciskiem: pakiety TX tej epoki z seq <= seq sa ignorowane
    void saveCut(uint32_t epoch, uint32_t seq);
    bool loadCut(uint32_t& epoch, uint32_t& seq);
};

#endif
