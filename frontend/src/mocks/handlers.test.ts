import { describe, expect, it } from "vitest";

import { coreApi } from "../api/core";
import { edgeApi } from "../api/edge";
import { ApiError } from "../api/errors";
import { mockFetch } from "./handlers";

describe("mock mode", () => {
  it("serves the edge production fixtures", async () => {
    const parts = await edgeApi.parts({ station_id: "WS-01" });
    expect(parts.map((p) => p.predicted_verdict).sort()).toEqual(["ERROR", "HOLD", "NOK", "OK"]);
    const shift = await edgeApi.currentShift("WS-01");
    expect(shift.kpi.total_parts).toBe(shift.kpi.ok_parts + shift.kpi.nok_parts + shift.kpi.hold_parts + shift.kpi.error_parts);
  });

  it("applies a correction without touching the prediction", async () => {
    const hold = (await edgeApi.parts()).find((p) => p.effective_verdict === "HOLD")!;
    const body = {
      new_verdict: "OK" as const,
      expected_current_verdict: "HOLD" as const,
      reason: "vérifié",
      actor_role: "operator" as const,
      physical_inspection: true,
    };
    const updated = await edgeApi.correctPart(hold.part_id, body);
    expect(updated.effective_verdict).toBe("OK");
    expect(updated.predicted_verdict).toBe("HOLD");
    await expect(edgeApi.correctPart(hold.part_id, body)).rejects.toMatchObject({ status: 409 });
  });

  it("serves the core fixtures, including simulated stations", async () => {
    const stations = await coreApi.stations();
    expect(stations).toHaveLength(12);
    expect(stations.filter((s) => !s.simulated).map((s) => s.station_id)).toEqual(["WS-01"]);
    expect((await coreApi.models()).length).toBeGreaterThan(0);
  });

  it("fails loudly on unmocked routes", async () => {
    await expect(mockFetch("core", "/api/v1/nope")).rejects.toBeInstanceOf(ApiError);
    await expect(mockFetch("core", "/api/v1/nope")).rejects.toMatchObject({ status: 501 });
  });
});
