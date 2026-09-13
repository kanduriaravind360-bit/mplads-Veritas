/**
 * Indian number formatting: lakh/crore grouping, compact rupee amounts and
 * amounts in words (English and Hindi). Every figure on screen goes through here.
 */

export type Lang = "en" | "hi";

const GROUPED = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const LAKH = 1e5;
const CRORE = 1e7;

export function count(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return GROUPED.format(Math.round(n));
}

/** ₹1,19,48,468 */
export function inrFull(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `₹${GROUPED.format(Math.round(n))}`;
}

function trim(value: number, digits: number): string {
  return value.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

/** ₹4,742 cr · ₹1.19 cr · ₹46.9 L · ₹12,500 */
export function inr(n: number | null | undefined, lang: Lang = "en"): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  const cr = lang === "hi" ? " करोड़" : " cr";
  const lk = lang === "hi" ? " लाख" : " L";
  if (a >= 1000 * CRORE) return `${sign}₹${GROUPED.format(Math.round(a / CRORE))}${cr}`;
  if (a >= 100 * CRORE) return `${sign}₹${trim(a / CRORE, 0)}${cr}`;
  if (a >= CRORE) return `${sign}₹${trim(a / CRORE, 2)}${cr}`;
  if (a >= LAKH) return `${sign}₹${trim(a / LAKH, a >= 10 * LAKH ? 1 : 2)}${lk}`;
  return `${sign}₹${GROUPED.format(Math.round(a))}`;
}

export function pct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

/** "24 of 159 (15.1%)": a rate always travels with its denominator. */
export function ofTotal(part: number, whole: number, lang: Lang = "en"): string {
  const share = whole ? ` (${pct(part / whole)})` : "";
  return lang === "hi"
    ? `${count(whole)} में से ${count(part)}${share}`
    : `${count(part)} of ${count(whole)}${share}`;
}

export function score(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toFixed(digits);
}

export function date(iso: string | null | undefined, lang: Lang = "en"): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function dateTime(iso: string | null | undefined, lang: Lang = "en"): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function monthLabel(ym: string, lang: Lang = "en"): string {
  const [y, m] = ym.split("-").map(Number);
  if (!y || !m) return ym;
  return new Date(y, m - 1, 1).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
    month: "short",
    year: "2-digit",
  });
}

// ---------------------------------------------------------------- words

const EN_ONES = [
  "",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
  "ten",
  "eleven",
  "twelve",
  "thirteen",
  "fourteen",
  "fifteen",
  "sixteen",
  "seventeen",
  "eighteen",
  "nineteen",
];
const EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];

function enBelow100(n: number): string {
  if (n < 20) return EN_ONES[n] ?? "";
  const tens = EN_TENS[Math.floor(n / 10)] ?? "";
  const ones = n % 10;
  return ones ? `${tens}-${EN_ONES[ones]}` : tens;
}

// Hindi numbers 1-99 are irregular, so they are listed rather than composed.
const HI_1_99 =
  "एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस " +
  "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस " +
  "इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ " +
  "इकसठ बासठ तिरेसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी " +
  "इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानबे बानबे तिरानबे चौरानबे पंचानबे छियानबे सत्तानबे अट्ठानबे निन्यानबे";
const HI_WORDS = HI_1_99.split(" ");

const UNITS = {
  en: { hundred: "hundred", thousand: "thousand", lakh: "lakh", crore: "crore", zero: "zero" },
  hi: { hundred: "सौ", thousand: "हज़ार", lakh: "लाख", crore: "करोड़", zero: "शून्य" },
};

function below100(n: number, lang: Lang): string {
  if (n <= 0) return "";
  return lang === "hi" ? (HI_WORDS[n - 1] ?? "") : enBelow100(n);
}

function below1000(n: number, lang: Lang): string {
  const parts: string[] = [];
  const hundreds = Math.floor(n / 100);
  if (hundreds) parts.push(`${below100(hundreds, lang)} ${UNITS[lang].hundred}`);
  const rest = n % 100;
  if (rest) parts.push(below100(rest, lang));
  return parts.join(" ");
}

/** Whole number in the Indian system: crore, lakh, thousand, hundred. */
export function numberInWords(value: number, lang: Lang = "en"): string {
  let n = Math.floor(Math.abs(value));
  if (n === 0) return UNITS[lang].zero;
  const parts: string[] = [];
  const crore = Math.floor(n / CRORE);
  n %= CRORE;
  if (crore) parts.push(`${numberInWords(crore, lang)} ${UNITS[lang].crore}`);
  const lakh = Math.floor(n / LAKH);
  n %= LAKH;
  if (lakh) parts.push(`${below100(lakh, lang)} ${UNITS[lang].lakh}`);
  const thousand = Math.floor(n / 1000);
  n %= 1000;
  if (thousand) parts.push(`${below100(thousand, lang)} ${UNITS[lang].thousand}`);
  if (n) parts.push(below1000(n, lang));
  return parts.join(" ");
}

export function rupeesInWords(value: number, lang: Lang = "en"): string {
  const words = numberInWords(Math.round(value), lang);
  return lang === "hi" ? `${words} रुपये` : `Rupees ${words}`;
}
