import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import hi from "@/locales/hi.json";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("locales", () => {
  it("Hindi has every English key and no extras", () => {
    expect(keys(hi).sort()).toEqual(keys(en).sort());
  });

  it("interpolation placeholders match", () => {
    const flat = (o: object) => Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce<any>((a, p) => a[p], o)]));
    const e = flat(en);
    const h = flat(hi);
    for (const key of Object.keys(e)) {
      const vars = (s: string) => (s.match(/{{\w+}}/g) ?? []).sort();
      expect(vars(h[key]), key).toEqual(vars(e[key]));
    }
  });
});
