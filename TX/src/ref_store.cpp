#include "ref_store.h"
#include "config.h"
#include "event_logger.h"
#include <LittleFS.h>
#include <string.h>
#include <stddef.h>

namespace {
    const uint32_t REF_MAGIC_V1 = 0x52454631;  // "REF1" - stary format (licznik cykli)
    const uint32_t REF_MAGIC_V2 = 0x52454632;  // "REF2" - czas w sekundach

    struct RefFileV1 {
        uint32_t magic;
        float value;
        uint16_t cyclesSinceRef;
        uint16_t reserved;
        uint32_t checksum;
    };

    struct RefFileV2 {
        uint32_t magic;
        float value;
        uint32_t secondsSinceRef;
        uint32_t checksum;
    };

    static_assert(sizeof(RefFileV1) == sizeof(RefFileV2), "formaty ref.bin musza miec ten sam rozmiar");

    uint32_t checksumOf(const uint8_t* p, size_t len) {
        uint32_t sum = 2166136261u;  // FNV-1a po polach bez checksum
        for (size_t i = 0; i < len; i++) {
            sum ^= p[i];
            sum *= 16777619u;
        }
        return sum;
    }
}

bool RefStore::save(const RefState& ref) {
    if (!eventLogger.isMounted() || !ref.valid) return false;

    RefFileV2 f;
    memset(&f, 0, sizeof(f));
    f.magic = REF_MAGIC_V2;
    f.value = ref.value;
    f.secondsSinceRef = ref.secondsSinceRef;
    f.checksum = checksumOf((const uint8_t*)&f, offsetof(RefFileV2, checksum));

    File file = LittleFS.open(REF_FILE_PATH, "w");
    if (!file) {
        DEBUG_PRINT("[REF] BLAD: nie mozna zapisac odniesienia");
        return false;
    }
    size_t written = file.write((const uint8_t*)&f, sizeof(f));
    file.flush();
    file.close();
    return written == sizeof(f);
}

bool RefStore::load(RefState& ref) {
    if (!eventLogger.isMounted()) return false;
    if (!LittleFS.exists(REF_FILE_PATH)) return false;

    File file = LittleFS.open(REF_FILE_PATH, "r");
    if (!file) return false;

    uint8_t raw[sizeof(RefFileV2)];
    size_t n = file.read(raw, sizeof(raw));
    file.close();

    if (n != sizeof(raw)) {
        DEBUG_PRINT("[REF] Plik odniesienia uszkodzony - ignoruje");
        return false;
    }

    float value = 0.0f;
    uint32_t seconds = 0;
    uint32_t magic;
    memcpy(&magic, raw, sizeof(magic));

    if (magic == REF_MAGIC_V2) {
        RefFileV2 f;
        memcpy(&f, raw, sizeof(f));
        if (f.checksum != checksumOf(raw, offsetof(RefFileV2, checksum))) {
            DEBUG_PRINT("[REF] Plik odniesienia uszkodzony - ignoruje");
            return false;
        }
        value = f.value;
        seconds = f.secondsSinceRef;
    } else if (magic == REF_MAGIC_V1) {
        RefFileV1 f;
        memcpy(&f, raw, sizeof(f));
        if (f.checksum != checksumOf(raw, offsetof(RefFileV1, checksum))) {
            DEBUG_PRINT("[REF] Plik odniesienia uszkodzony - ignoruje");
            return false;
        }
        value = f.value;
        seconds = (uint32_t)f.cyclesSinceRef * 43200UL;  // stary format liczyl cykle po 12 h;  // migracja ze starego formatu
    } else {
        DEBUG_PRINT("[REF] Plik odniesienia uszkodzony - ignoruje");
        return false;
    }

    if (!(value >= MIN_VALID_DISTANCE && value <= MAX_VALID_DISTANCE)) {
        return false;
    }

    ref.value = value;
    ref.valid = true;
    ref.secondsSinceRef = seconds;
    ref.rejectedCycles = 0;
    ref.deadzoneCycles = 0;
    ref.risePending = 0;
    ref.riseValue = 0.0f;
    return true;
}
