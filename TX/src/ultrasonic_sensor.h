#ifndef ULTRASONIC_SENSOR_H
#define ULTRASONIC_SENSOR_H

#include <Arduino.h>
#include "config.h"

class UltrasonicSensor {
public:
    UltrasonicSensor(uint8_t trigPin, uint8_t echoPin);
    
    void begin();
    float measureDistanceCm();
    bool isValidReading(float distance);
    
private:
    uint8_t _trigPin;
    uint8_t _echoPin;
    
    void sendTriggerPulse();
    uint32_t measureEchoDuration();
};

#endif
