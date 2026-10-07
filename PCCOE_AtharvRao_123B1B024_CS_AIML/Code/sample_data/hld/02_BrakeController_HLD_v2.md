# AUTOSAR High-Level Design Document: Brake Controller Subsystem
Document Version: 2.0.0
Classification: Synthetic Technical Fixture (Revision Update)

## 1. Subsystem Architecture Overview (Revision 2.0)
The Brake Controller Subsystem has been updated to support high-voltage regenerative braking integration.

Primary software component `BrakeController` (alias `BrakeCtrl`) remains the core controller.

### 1.1 Updated Components and Interfaces
- `BrakeController` is a `SOFTWARE_COMPONENT`.
- `WheelSpeedSensor` is a `SOFTWARE_COMPONENT`.
- `RegenBrakeModule` is a new `SOFTWARE_COMPONENT` introduced in Revision 2.0.

- `WheelSpeedInterface` is an `INTERFACE`.
- `BrakeCommandInterface_v2` is an updated `INTERFACE` superseding `BrakeCommandInterface`.
- `RegenStatusInterface` is an `INTERFACE` carrying energy recovery telemetry.

## 2. Updated Dependencies
- `BrakeController` `REQUIRES` `WheelSpeedInterface`.
- `BrakeController` `PROVIDES` `BrakeCommandInterface_v2`.
- `BrakeController` `USES` `RegenStatusInterface`.
- `RegenBrakeModule` `PROVIDES` `RegenStatusInterface`.

## 3. Added Signals
- `BrakeTemperatureSignal` is a `SIGNAL` carried by `BrakeCommandInterface_v2`.
- `RegenTorqueSignal` is a `SIGNAL` carried by `RegenStatusInterface`.
