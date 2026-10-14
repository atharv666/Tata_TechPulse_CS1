# Synthetic Ground Truth and Review Protocol

## Source

The ground truth is derived only from the synthetic fixtures in `../Input_Data/` (`BrakeController_HLD_v1.md`,
`BrakeController_HLD_v2.md`, `ABS_Subsystem_HLD.md`). It was written by the student and has not been independently reviewed.

## Expected facts used for manual review

| Category | Expected supported fact | Source evidence |
| --- | --- | --- |
| Entity | `BrakeController` is a `SOFTWARE_COMPONENT` | v1 §1.1 |
| Relationship | `BrakeController REQUIRES WheelSpeedInterface` | v1 §2 |
| Relationship | `BrakeController USES VehicleStateInterface` | v1 §2 |
| Relationship | `BrakeController PROVIDES BrakeCommandInterface` | v1 §2 |
| Dependency | `ESP_Module DEPENDS_ON BrakeController` | v1 §5 (a candidate inferred relation, not a stated fact) |
| Interface/signal | `WheelSpeedInterface CARRIES WheelSpeedSignal` | v1 §3 |
| Alias | `BrakeCtrl` and `BrakeControllerSWC` refer to `BrakeController` | v1 introductory paragraph |
| ABS | `AbsController REQUIRES WheelSpeedInterface` through port `P_WheelSpeed_In` | ABS §2 |
| Table value | DID `0xF40D` is `VehicleSpeed`, length 1 | ABS §3.2 |
| Timing | `Run_SlipEstimation` runs every 10 ms; degraded mode holds the last valve command for at most 50 ms | ABS §3.1 |
| Revision | `BrakeCommandInterface` becomes `BrakeCommandInterface_v2`; `RegenBrakeModule` and `RegenStatusInterface` are added | v2 §1.1, §2 |
| Insufficient evidence | Maximum braking torque in N·m; battery-management charging specification | Absent from every document: the system must refuse |

## Manual scoring rules

For each reviewed result:

1. **Correct** only if the claim agrees with the source document.
2. **Grounded** only if the citation points to the right document version and a supporting excerpt.
3. **Safe** if extraction type (explicit / inferred) and validation status are visible and truthful.
4. **Unsupported** if the answer adds a fact absent from the source, uses a wrong citation, or hides insufficient evidence.

Report the measures separately and state their denominators:

* claim correctness = correct claims / reviewed claims;
* citation coverage = material claims with a valid citation / material claims;
* unsupported-claim rate = unsupported claims / reviewed claims;
* review correction rate = corrected facts / reviewed facts.

Do not combine them into one "accuracy" figure.

## Scored results of the recorded demonstration (14 October 2026)

| Question / action | Correct | Grounded | Safe | Notes |
| --- | :---: | :---: | :---: | --- |
| "What does BrakeController require?" → `WheelSpeedInterface` | yes | yes (2 citations) | yes (*EXPLICIT · PENDING*) | The question matches the `REQUIRES` fact; the `USES` fact is a different relationship |
| DID of the vehicle-speed signal → `0xF40D` | yes | yes (ABS §3.2) | yes | The length claim (1) was verified at the 60 % support threshold |
| Maximum braking torque in N·m | — | — | yes | Correctly refused: *Insufficient evidence* |
| "What does AbsController require?" (graph only) → `WheelSpeedInterface` | yes | yes | yes | |
| Impact of `WheelSpeedInterface` (2 hops) | plausible | yes (each path cites its facts) | yes | 4 direct and 7 indirect results; whether each is a real impact is an engineering judgement |
| Review of extracted facts | 2 verified, 1 rejected, 1 corrected | — | — | `ABS` and `ESP` extracted as generic `FUNCTION` entities were judged unwanted; the correction changed a type |
| Revision comparison | rename `BrakeCommandInterface` → `_v2` detected as *possible rename*; additions detected | yes | yes | 56 removals include entities that v2 merely stops mentioning |

Scored: 3 of 3 answerable demonstration questions correct and grounded; 1 of 1 unanswerable question refused. This is far too
small a sample for a percentage; the larger measurement is the 23-question evaluation in `EVALUATION_RESULTS.md`.
