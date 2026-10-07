import { describe, expect, it } from "vitest";
import { statusTone } from "./StatusBadge";

describe("statusTone", () => {
  it("uses textual status semantics before extraction color", () => {
    expect(
      statusTone({ validation_state: "HUMAN_VERIFIED", extraction_type: "INFERRED", confidence: 0.2 })
    ).toBe("green");
    expect(
      statusTone({ validation_state: "PENDING", extraction_type: "EXPLICIT", confidence: 0.9 })
    ).toBe("blue");
    expect(
      statusTone({ validation_state: "PENDING", extraction_type: "INFERRED", confidence: 0.9 })
    ).toBe("orange");
    expect(
      statusTone({ validation_state: "REJECTED", extraction_type: "EXPLICIT", confidence: 0.9 })
    ).toBe("red");
  });

  it("classifies lower confidence facts as orange tone", () => {
    expect(
      statusTone({ validation_state: "PENDING", extraction_type: "EXPLICIT", confidence: 0.5 })
    ).toBe("orange");
    expect(
      statusTone({ validation_state: "PENDING", extraction_type: "EXPLICIT", confidence: 0.69 })
    ).toBe("orange");
  });

  it("prioritizes REJECTED status over explicit high confidence", () => {
    expect(
      statusTone({ validation_state: "REJECTED", extraction_type: "EXPLICIT", confidence: 1.0 })
    ).toBe("red");
  });
});
