import { describe, expect, it } from "vitest";
import { count, inr, inrFull, numberInWords, ofTotal, rupeesInWords } from "./format";

describe("Indian formatting", () => {
  it("groups in lakh and crore", () => {
    expect(inrFull(11948468)).toBe("₹1,19,48,468");
    expect(count(77312)).toBe("77,312");
  });

  it("compacts amounts", () => {
    expect(inr(11948468)).toBe("₹1.19 cr");
    expect(inr(4694298)).toBe("₹46.9 L");
    expect(inr(150000)).toBe("₹1.5 L");
    expect(inr(12500)).toBe("₹12,500");
    expect(inr(47424623417.99)).toBe("₹4,742 cr");
    expect(inr(20000000, "hi")).toBe("₹2 करोड़");
  });

  it("writes amounts in words", () => {
    expect(numberInWords(11948468)).toBe(
      "one crore nineteen lakh forty-eight thousand four hundred sixty-eight",
    );
    expect(numberInWords(47424623418)).toBe(
      "four thousand seven hundred forty-two crore forty-six lakh twenty-three thousand four hundred eighteen",
    );
    expect(rupeesInWords(250000)).toBe("Rupees two lakh fifty thousand");
    expect(numberInWords(1500000, "hi")).toBe("पंद्रह लाख");
    expect(numberInWords(20000000, "hi")).toBe("दो करोड़");
    expect(numberInWords(99, "hi")).toBe("निन्यानबे");
  });

  it("always shows the denominator", () => {
    expect(ofTotal(24, 159)).toBe("24 of 159 (15.1%)");
    expect(ofTotal(0, 0)).toBe("0 of 0");
  });
});
