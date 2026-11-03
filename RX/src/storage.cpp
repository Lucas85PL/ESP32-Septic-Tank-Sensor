#include "storage.h"

#define NVS_NAMESPACE "rx"
#define MAX_AGE_SECONDS 100000000UL   // ~3 lata (czas w RX jest 64-bitowy - brak ograniczenia 49,7 dnia)

void Storage::saveSnapshot(float rawDistanceCm, uint32_t ageSeconds) {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) {
        DEBUG_PRINT("[STORAGE] Blad otwarcia NVS");
        return;
    }
    prefs.putFloat("dist", rawDistanceCm);
    prefs.putUInt("age", ageSeconds);
    prefs.putBool("valid", true);
    prefs.end();
}

bool Storage::load(float& rawDistanceCm, uint32_t& ageSeconds) {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return false;   // rw: tworzy namespace przy 1. uruchomieniu (bez błędu NOT_FOUND)
    bool valid = prefs.getBool("valid", false);
    if (valid) {
        rawDistanceCm = prefs.getFloat("dist", -1.0f);
        ageSeconds = prefs.getUInt("age", 0);
        if (ageSeconds > MAX_AGE_SECONDS) ageSeconds = MAX_AGE_SECONDS;
    }
    prefs.end();
    return valid;
}

void Storage::saveHistory(const HistBlob& blob) {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return;
    prefs.putBytes("hist", &blob, sizeof(blob));
    prefs.end();
}

bool Storage::loadHistory(HistBlob& blob) {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return false;
    bool ok = false;
    if (prefs.getBytesLength("hist") == sizeof(HistBlob)) {
        prefs.getBytes("hist", &blob, sizeof(blob));
        ok = blob.count >= 1 && blob.count <= MEAS_HIST_MAX;
    }
    prefs.end();
    return ok;
}

void Storage::saveCut(uint32_t epoch, uint32_t seq) {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return;
    prefs.putUInt("cute", epoch);
    prefs.putUInt("cuts", seq);
    prefs.putBool("cutv", true);
    prefs.end();
}

bool Storage::loadCut(uint32_t& epoch, uint32_t& seq) {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return false;
    bool valid = prefs.getBool("cutv", false);
    if (valid) {
        epoch = prefs.getUInt("cute", 0);
        seq = prefs.getUInt("cuts", 0);
    }
    prefs.end();
    return valid;
}

void Storage::clear() {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return;
    prefs.clear();
    prefs.end();
}
