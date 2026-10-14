# AUTOSAR High-Level Design Document: Brake Controller Subsystem
Document Version: 1.0.0
Classification: Synthetic Technical Fixture

## 1. Subsystem Architecture Overview
The Brake Controller Subsystem provides anti-lock braking (ABS) and electronic stability control (ESP) processing for automotive platforms.

The primary software component is `BrakeController` (also referenced as `BrakeCtrl` or `BrakeControllerSWC`).

### 1.1 Components and Interfaces
- `BrakeController` is a `SOFTWARE_COMPONENT` that manages braking control loops.
- `WheelSpeedSensor` is a `SOFTWARE_COMPONENT` that reads wheel rotation speed.
- `ABS_Module` is a `SOFTWARE_COMPONENT` that modulates hydraulic brake pressure during slippage.
- `ESP_Module` is a `SOFTWARE_COMPONENT` that provides dynamic stability management.

- `WheelSpeedInterface` is an `INTERFACE` that carries wheel speed data.
- `BrakeCommandInterface` is an `INTERFACE` that carries brake force request signals.
- `VehicleStateInterface` is an `INTERFACE` that carries overall vehicle motion state.

## 2. Dependencies and Port Allocations
- `BrakeController` `REQUIRES` `WheelSpeedInterface` through input port `P_WheelSpeed_In`.
- `BrakeController` `USES` `VehicleStateInterface` through input port `P_VehicleState_In`.
- `BrakeController` `PROVIDES` `BrakeCommandInterface` through output port `P_BrakeCmd_Out`.
- `WheelSpeedSensor` `PROVIDES` `WheelSpeedInterface` through output port `P_SensorSpeed_Out`.
- `ABS_Module` `CONSUMES` `BrakeCommandInterface` to regulate brake pressure.

## 3. Signal and Data Element Catalog
- `WheelSpeedSignal` is a `SIGNAL` carried by `WheelSpeedInterface`.
- `BrakePressureSignal` is a `SIGNAL` carried by `BrakeCommandInterface`.
- `VehicleSpeedData` is a `DATA_ELEMENT` defined within `VehicleStateInterface`.

## 4. Runnables and Execution Functions
- `CalculateBrakePressureRunnable` is a `RUNNABLE` executed periodically inside `BrakeController`.
- `ProcessWheelSpeedFunction` is a `FUNCTION` that computes RPM values from raw sensor pulses.

## 5. Candidate Inferred Relations and Integrity Rules
- `ESP_Module` `DEPENDS_ON` `BrakeController` for emergency stability interventions.
- `BrakeController` `PART_OF` `ChassisControlDomain`.

