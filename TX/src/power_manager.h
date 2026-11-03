#ifndef POWER_MANAGER_H
#define POWER_MANAGER_H

#include <Arduino.h>
#include <esp_sleep.h>
#include "config.h"

class PowerManager {
public:
    static void enterDeepSleep(uint64_t sleepTimeSeconds);
    static void enterDeepSleep();
    static void printWakeupReason();
    static const char* getWakeupReasonString();
    static bool isWakeupFromDeepSleep();
    // "TIMER" po wybudzeniu z deep sleep, w przeciwnym razie nazwa przyczyny resetu (POWERON, BROWNOUT, PANIC, ...)
    static const char* getBootReasonString();
    // true tylko dla recznego uruchomienia (zasilanie / przycisk EN) - wtedy czlowiek jest przy plytce
    static bool isManualBoot();
    
private:
    static void configureWakeupSource(uint64_t sleepTimeSeconds);
};

#endif
