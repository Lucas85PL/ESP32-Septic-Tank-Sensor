#include "power_manager.h"
#include <esp_system.h>

void PowerManager::configureWakeupSource(uint64_t sleepTimeSeconds) {
    esp_sleep_enable_timer_wakeup(sleepTimeSeconds * 1000000ULL);
    DEBUG_PRINTF("[POWER] Ustawiono wybudzenie za %llu sekund\n", sleepTimeSeconds);
}

const char* PowerManager::getWakeupReasonString() {
    switch (esp_sleep_get_wakeup_cause()) {
        case ESP_SLEEP_WAKEUP_TIMER:   return "TIMER";
        case ESP_SLEEP_WAKEUP_EXT0:    return "EXT0";
        case ESP_SLEEP_WAKEUP_EXT1:    return "EXT1";
        case ESP_SLEEP_WAKEUP_TOUCHPAD: return "TOUCHPAD";
        case ESP_SLEEP_WAKEUP_ULP:     return "ULP";
        default:                       return "RESET";
    }
}

void PowerManager::printWakeupReason() {
    esp_sleep_wakeup_cause_t wakeupReason = esp_sleep_get_wakeup_cause();
    
    switch (wakeupReason) {
        case ESP_SLEEP_WAKEUP_TIMER:
            DEBUG_PRINT("[POWER] Wybudzenie: TIMER (deep sleep)");
            break;
        case ESP_SLEEP_WAKEUP_EXT0:
            DEBUG_PRINT("[POWER] Wybudzenie: EXT0 (przycisk)");
            break;
        case ESP_SLEEP_WAKEUP_EXT1:
            DEBUG_PRINT("[POWER] Wybudzenie: EXT1 (przycisk)");
            break;
        case ESP_SLEEP_WAKEUP_TOUCHPAD:
            DEBUG_PRINT("[POWER] Wybudzenie: TOUCHPAD");
            break;
        case ESP_SLEEP_WAKEUP_ULP:
            DEBUG_PRINT("[POWER] Wybudzenie: ULP");
            break;
        default:
            DEBUG_PRINT("[POWER] Wybudzenie: RESET / ZASILANIE");
            break;
    }
}

const char* PowerManager::getBootReasonString() {
    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER) {
        return "TIMER";
    }
    switch (esp_reset_reason()) {
        case ESP_RST_POWERON:   return "POWERON";
        case ESP_RST_EXT:       return "EXT";
        case ESP_RST_SW:        return "SW";
        case ESP_RST_PANIC:     return "PANIC";
        case ESP_RST_INT_WDT:   return "INT_WDT";
        case ESP_RST_TASK_WDT:  return "TASK_WDT";
        case ESP_RST_WDT:       return "WDT";
        case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
        case ESP_RST_BROWNOUT:  return "BROWNOUT";
        case ESP_RST_SDIO:      return "SDIO";
        default:                return "UNKNOWN";
    }
}

bool PowerManager::isManualBoot() {
    if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_UNDEFINED) {
        return false;
    }
    esp_reset_reason_t r = esp_reset_reason();
    return r == ESP_RST_POWERON || r == ESP_RST_EXT;
}

bool PowerManager::isWakeupFromDeepSleep() {
    return esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER;
}

void PowerManager::enterDeepSleep(uint64_t sleepTimeSeconds) {
    DEBUG_PRINT("========================================");
    DEBUG_PRINT("[POWER] Przygotowanie do deep sleep");
    DEBUG_PRINTF("[POWER] Czas snu: %llu sekund\n", sleepTimeSeconds);
    DEBUG_PRINT("========================================");
    
    delay(100);
    
    Serial.flush();
    
    configureWakeupSource(sleepTimeSeconds);
    
    DEBUG_PRINT("[POWER] Wchodzę w deep sleep... Do zobaczenia!");
    delay(100);
    Serial.flush();

    digitalWrite(PIN_MOSFET, LOW);  // Zasilanie sensora OFF
    delay(10);

    esp_deep_sleep_start();
}

void PowerManager::enterDeepSleep() {
    enterDeepSleep(DEEP_SLEEP_SECONDS);
}
