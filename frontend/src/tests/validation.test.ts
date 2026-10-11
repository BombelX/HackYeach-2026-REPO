import { describe, expect, it } from "vitest";
import { fold, parseAmount, validNrb } from "../services/validation";
describe("Money and Polish account validation", () => {
  it("uses integer grosze, accepts Polish decimals, rejects precision loss and malformed inputs", () => {
    expect(parseAmount("1 250,01")).toBe(125001);
    expect(parseAmount("0,01")).toBe(1);
    for (const value of ["0", "-1", "1.999", "1e3", "NaN", "1,2,3", ""])
      expect(parseAmount(value)).toBeNull();
  });
  it("validates all NRB digits, not just their count", () => {
    expect(validNrb("61 1090 1014 0000 0712 1981 2874")).toBe(true);
    expect(validNrb("62 1090 1014 0000 0712 1981 2874")).toBe(false);
    expect(validNrb("12 3456 7890 1234 5678 9012 3456")).toBe(false);
  });
  it("finds Polish titles without requiring accents", () => {
    expect(fold("Łódź · październik")).toBe("lodz · pazdziernik");
  });
});
