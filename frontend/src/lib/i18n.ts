import i18n from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";
import en from "@/locales/en.json";
import hi from "@/locales/hi.json";
import type { Lang } from "@/lib/format";

const LANG_KEY = "sentinel.lang";

function initialLang(): Lang {
  try {
    return localStorage.getItem(LANG_KEY) === "hi" ? "hi" : "en";
  } catch {
    return "en";
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, hi: { translation: hi } },
  lng: initialLang(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

document.documentElement.lang = i18n.language;

export function setLang(lang: Lang): void {
  void i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* ignore */
  }
}

/** `t` plus the active language, typed for the formatters. */
export function useLang(): { t: ReturnType<typeof useTranslation>["t"]; lang: Lang } {
  const { t, i18n: instance } = useTranslation();
  return { t, lang: instance.language === "hi" ? "hi" : "en" };
}

/** Pick the Hindi or English variant of an API field. */
export function pick<T>(lang: Lang, en: T, hi: T | null | undefined): T {
  return lang === "hi" && hi !== null && hi !== undefined ? hi : en;
}

export default i18n;
