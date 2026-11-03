#include "meas_history.h"
#include "config.h"
#include "event_logger.h"
#include <LittleFS.h>
#include <esp_system.h>
#include <string.h>
#include <stddef.h>

namespace {
    struct Entry {
        float value;      // surowa odleglosc [cm]
        int32_t t;        // czas pomiaru na osi czasu TX [s] (g.clock w chwili akceptacji; po resecie ujemny)
        uint8_t synth;    // 1 = sztuczne 25.0 cm (strefa martwa)
    };

    struct State {
        bool loaded;      // historia odtworzona z flash po cold boot
        bool curPt;       // ostatni punkt pochodzi z biezacego cyklu (ponowienie wysylki go zastepuje)
        int32_t clock;    // os czasu TX [s] (suma zadanych snow + pracy)
        uint32_t epoch;
        uint32_t seq;
        uint8_t count;
        Entry e[MEAS_HIST_MAX];   // najstarszy pierwszy
    };

    RTC_DATA_ATTR State g;

    const uint32_t HIST_MAGIC = 0x48495332;  // "HIS2"

    struct FileEntry {
        float value;
        uint32_t age;     // wiek wzgledem NAJNOWSZEGO punktu [s]
        uint8_t synth;
        uint8_t pad[3];
    };

    struct HistFile {
        uint32_t magic;
        uint32_t epoch;
        uint32_t seq;
        uint8_t count;
        uint8_t pad[3];
        FileEntry e[MEAS_HIST_MAX];
        uint32_t checksum;
    };

    uint32_t checksumOf(const uint8_t* p, size_t len) {
        uint32_t sum = 2166136261u;  // FNV-1a (jak w ref_store)
        for (size_t i = 0; i < len; i++) {
            sum ^= p[i];
            sum *= 16777619u;
        }
        return sum;
    }

    uint32_t newEpoch() {
        uint32_t e = 0;
        while (e == 0) e = esp_random();
        return e;
    }

    void saveToFlash() {
        if (!eventLogger.isMounted()) return;

        HistFile f;
        memset(&f, 0, sizeof(f));
        f.magic = HIST_MAGIC;
        f.epoch = g.epoch;
        f.seq = g.seq;
        f.count = g.count;
        const int32_t newest = g.count ? g.e[g.count - 1].t : 0;
        for (uint8_t i = 0; i < g.count; i++) {
            f.e[i].value = g.e[i].value;
            f.e[i].age = (uint32_t)(newest - g.e[i].t);
            f.e[i].synth = g.e[i].synth;
        }
        f.checksum = checksumOf((const uint8_t*)&f, offsetof(HistFile, checksum));

        const char* tmpPath = "/hist.tmp";
        File file = LittleFS.open(tmpPath, "w");
        if (!file) {
            DEBUG_PRINT("[HIST] BLAD: nie mozna zapisac historii");
            return;
        }
        size_t written = file.write((const uint8_t*)&f, sizeof(f));
        file.flush();
        file.close();
        if (written != sizeof(f)) {
            LittleFS.remove(tmpPath);
            DEBUG_PRINT("[HIST] BLAD: zapis historii niepelny");
            return;
        }
        LittleFS.remove(HIST_FILE_PATH);
        if (!LittleFS.rename(tmpPath, HIST_FILE_PATH)) {
            LittleFS.remove(tmpPath);
            DEBUG_PRINT("[HIST] BLAD: rename historii nieudany");
        }
    }

    // Brak / uszkodzony plik => nowa epoka i numeracja od 0 (RX rozpozna zmiane epoki i przyjmie pakiet).
    void loadFromFlash() {
        g.count = 0;
        g.curPt = false;
        g.epoch = 0;
        g.seq = 0;

        if (eventLogger.isMounted()) {
            LittleFS.remove("/hist.tmp");   // niedokonczony zapis po utracie zasilania
            if (LittleFS.exists(HIST_FILE_PATH)) {
                File file = LittleFS.open(HIST_FILE_PATH, "r");
                if (file) {
                    HistFile f;
                    size_t n = file.read((uint8_t*)&f, sizeof(f));
                    file.close();
                    if (n == sizeof(f) && f.magic == HIST_MAGIC && f.count <= MEAS_HIST_MAX && f.epoch != 0 &&
                        f.checksum == checksumOf((const uint8_t*)&f, offsetof(HistFile, checksum))) {
                        g.epoch = f.epoch;
                        g.seq = f.seq;
                        g.count = f.count;
                        // Wiek najnowszego punktu po resecie jest nieznany - zakladamy pol okresu pomiarowego.
                        for (uint8_t i = 0; i < f.count; i++) {
                            g.e[i].value = f.e[i].value;
                            g.e[i].t = g.clock - (int32_t)(HIST_ASSUMED_GAP_S + f.e[i].age);
                            g.e[i].synth = f.e[i].synth;
                        }
                        DEBUG_PRINTF("[HIST] Przywrocono historie z flash: %u pkt, epoka %08lX, seq %lu\n",
                                     (unsigned)g.count, (unsigned long)g.epoch, (unsigned long)g.seq);
                        return;
                    }
                    DEBUG_PRINT("[HIST] Plik historii uszkodzony - nowa epoka");
                }
            }
        }
        g.epoch = newEpoch();
        g.seq = 0;
        DEBUG_PRINTF("[HIST] Brak historii - nowa epoka %08lX\n", (unsigned long)g.epoch);
    }
}

namespace MeasHistory {

void resetRtc() {
    memset(&g, 0, sizeof(g));
}

void advanceClock(uint32_t elapsedSeconds) {
    g.clock += (int32_t)elapsedSeconds;
}

void begin() {
    if (!g.loaded) {
        loadFromFlash();
        g.loaded = true;
    }
}

void onAccepted(const MeasurementResult& result, bool prevValid, float prevValue, uint8_t prevRejected, bool isRetry) {
    if (g.epoch == 0) {          // gdyby begin() nie zostalo wywolane
        g.epoch = newEpoch();
        g.seq = 0;
    }

    // Wzrost odleglosci (wywoz) albo reset odniesienia po odrzuconych cyklach: stara historia napelniania jest bezuzyteczna.
    const bool jump = prevValid && ((result.value - prevValue) > RISE_NOISE_CM || prevRejected >= MAX_REJECTED_CYCLES);
    if (jump) {
        g.count = 0;
        g.curPt = false;
        DEBUG_PRINT("[HIST] Zmiana poziomu (wywoz / reset odniesienia) - historia wyczyszczona");
    }

    const uint8_t synth = (result.status == CycleStatus::BELOW_MIN_RANGE) ? 1 : 0;

    if (isRetry && g.curPt && g.count > 0) {
        // swiezy pomiar przy ponowieniu zastepuje oczekujacy punkt tego samego cyklu (ten sam seq)
        Entry& last = g.e[g.count - 1];
        last.value = result.value;
        last.t = g.clock;
        last.synth = synth;
    } else {
        if (g.count == MEAS_HIST_MAX) {
            memmove(&g.e[0], &g.e[1], sizeof(Entry) * (MEAS_HIST_MAX - 1));
            g.count--;
        }
        g.e[g.count].value = result.value;
        g.e[g.count].t = g.clock;
        g.e[g.count].synth = synth;
        g.count++;
        g.seq++;
    }
    g.curPt = true;
    saveToFlash();
    DEBUG_PRINTF("[HIST] Punkt zatwierdzony: %.2f cm, seq %lu, punktow %u\n", result.value, (unsigned long)g.seq, (unsigned)g.count);
}

size_t buildPacket(MeasurementPacketV2& packet, uint8_t validReadings, float fallbackValue) {
    memset(&packet, 0, sizeof(packet));
    packet.magic = MEAS_V2_MAGIC;
    packet.version = MEAS_V2_VERSION;
    packet.packetId = 0;                 // ustawia EspNowManager przy wysylce
    packet.validReadings = validReadings;
    packet.epoch = g.epoch;
    packet.seq = g.seq;

    uint8_t n = 0;
    for (int i = (int)g.count - 1; i >= 0 && n < MEAS_HIST_MAX; i--) {
        float v = g.e[i].value * 10.0f + 0.5f;
        if (v < 0) v = 0;
        if (v > 65535.0f) v = 65535.0f;
        int32_t age = g.clock - g.e[i].t;
        packet.pts[n].distDeci = (uint16_t)v;
        packet.pts[n].ageSec = age > 0 ? (uint32_t)age : 0;
        packet.pts[n].flags = g.e[i].synth ? MEAS_FLAG_SYNTHETIC : 0;
        n++;
    }
    if (n == 0) {
        float v = fallbackValue * 10.0f + 0.5f;
        packet.pts[0].distDeci = (uint16_t)(v < 0 ? 0 : (v > 65535.0f ? 65535.0f : v));
        packet.pts[0].ageSec = 0;
        packet.pts[0].flags = 0;
        n = 1;
    }
    packet.count = n;
    return MEAS_V2_LEN(n);
}

uint8_t count() { return g.count; }
uint32_t seq() { return g.seq; }
uint32_t epoch() { return g.epoch; }

}  // namespace MeasHistory
