# Synthetic Ground Truth and Review Protocol

## Source

The ground truth is derived solely from `../Input_Data/BrakeController_HLD_v1.md`, with revision-difference checks using the v2 fixture present in `Code/` for comparison workflows.

## Expected facts for manual demo review

| Category | Expected supported fact | Required source evidence |
| --- | --- | --- |
| Entity | BrakeController is a SOFTWARE_COMPONENT | Section 1.1 |
| Relationship | BrakeController REQUIRES WheelSpeedInterface | Section 2 |
| Relationship | BrakeController USES VehicleStateInterface | Section 2 |
| Relationship | BrakeController PROVIDES BrakeCommandInterface | Section 2 |
| Dependency | ESP_Module DEPENDS_ON BrakeController | Section 5; classify as inferred/candidate when generated as such |
| Interface/signal | WheelSpeedInterface carries WheelSpeedSignal | Section 3 |
| Alias | BrakeCtrl and BrakeControllerSWC refer to BrakeController | Introductory paragraph |
| Insufficient evidence | Battery-management charging specification | Must return insufficient evidence; this fact is absent |

## Manual scoring rules

For each screenshot-backed result:

1. Mark **correct** only if the claim agrees with the source document.
2. Mark **grounded** only if the returned citation points to the correct document version and supporting excerpt.
3. Mark **safe** if explicit/inferred status and validation status are visible and truthful.
4. Mark **unsupported** if the answer adds a fact absent from the source, uses a wrong citation, or hides insufficient evidence.

Report results separately:

- claim correctness = correct claims / reviewed claims;
- citation coverage = material claims with valid citations / material claims;
- unsupported-claim rate = unsupported claims / reviewed claims;
- review correction rate = corrected facts / reviewed facts.

Do not combine these into one “accuracy” figure without explaining the denominator and review method.
