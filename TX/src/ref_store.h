#ifndef REF_STORE_H
#define REF_STORE_H

#include <Arduino.h>
#include "measurement.h"

// Trwaly zapis odniesienia (RefState) w LittleFS (/ref.bin).
// RTC_DATA_ATTR przezywa tylko deep sleep - po resecie / utracie zasilania odniesienie jest odtwarzane stad,
// dzieki czemu nadajnik nie musi ufac pierwszemu pomiarowi po wlaczeniu (bootstrap).
namespace RefStore {
    bool save(const RefState& ref);
    bool load(RefState& ref);
}

#endif
