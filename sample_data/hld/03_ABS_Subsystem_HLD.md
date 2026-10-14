# ABS Subsystem High-Level Design
Document Version: 1.2.0
Classification: Synthetic Technical Fixture
Status: Approved

## 1. Overview
The anti-lock braking subsystem is implemented by the software component `AbsController` (also referenced as `ABSCtrl`). It reads wheel speeds, estimates wheel slip and requests brake pressure modulation. All timing values in this document refer to the ECU `BrakeEcu`.

### 1.1 Components
- `AbsController` is a `SOFTWARE_COMPONENT` that coordinates slip control.
- `SlipEstimator` is a `FUNCTION` that computes the slip ratio of each wheel.
- `HydraulicValveDriver` is a `SOFTWARE_COMPONENT` that actuates the hydraulic valves.
- `BrakeEcu` is an `ECU` that hosts the ABS software components.

### 1.2 Interfaces
- `WheelSpeedInterface` is an `INTERFACE` that carries wheel speed data.
- `ValveCommandInterface` is an `INTERFACE` that carries valve actuation requests.

## 2. Dependencies
- `AbsController` `REQUIRES` `WheelSpeedInterface` through input port `P_WheelSpeed_In`.
- `AbsController` `PROVIDES` `ValveCommandInterface` through output port `P_ValveCmd_Out`.
- `HydraulicValveDriver` `CONSUMES` `ValveCommandInterface`.
- `AbsController` `PART_OF` `BrakeEcu`.

## 3. Timing and Diagnostics
### 3.1 Timing
The runnable `Run_SlipEstimation` is executed every 10 ms. The valve command is updated every 5 ms after the slip estimation has completed. If the slip estimation misses its deadline twice in a row the controller switches to the degraded mode and signals a fault. The degraded mode keeps the last valid valve command for at most 50 ms before releasing brake pressure.

### 3.2 Diagnostics
Diagnostic services follow ISO 14229. Service `0x22` reads data identifiers and service `0x2E` writes them. The following identifiers are supported.

| DID | Name | Length |
| --- | --- | --- |
| 0xF190 | VehicleIdentificationNumber | 17 |
| 0xF18C | EcuSerialNumber | 12 |
| 0xF40D | VehicleSpeed | 1 |
