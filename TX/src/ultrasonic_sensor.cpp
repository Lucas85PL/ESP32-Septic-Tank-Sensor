#include "ultrasonic_sensor.h"

UltrasonicSensor::UltrasonicSensor(uint8_t trigPin, uint8_t echoPin)
    : _trigPin(trigPin), _echoPin(echoPin) {
}

void UltrasonicSensor::begin() {
    pinMode(_trigPin, OUTPUT);
    pinMode(_echoPin, INPUT);
    digitalWrite(_trigPin, LOW);
    delay(10);
}

void UltrasonicSensor::sendTriggerPulse() {
    digitalWrite(_trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(_trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(_trigPin, LOW);
}

uint32_t UltrasonicSensor::measureEchoDuration() {
    return pulseIn(_echoPin, HIGH, MAX_TIMEOUT_US);
}

float UltrasonicSensor::measureDistanceCm() {
    sendTriggerPulse();
    uint32_t duration = measureEchoDuration();
    
    if (duration == 0) {
        DEBUG_PRINT("[SENSOR] Timeout - brak echa");
        return INVALID_READING;
    }
    
    float distance = (duration * SOUND_SPEED_CM_PER_US) / 2.0f;
    return distance;
}

bool UltrasonicSensor::isValidReading(float distance) {
    return distance >= MIN_VALID_DISTANCE && distance <= MAX_VALID_DISTANCE;
}
