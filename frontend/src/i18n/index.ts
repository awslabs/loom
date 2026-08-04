import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import ja from "./locales/ja.json";

export const SUPPORTED_LANGUAGES = ["en", "ja"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const resources = {
  en: { translation: en },
  ja: { translation: ja },
} as const;

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "en",
    supportedLngs: [...SUPPORTED_LANGUAGES],
    interpolation: {
      // React already escapes rendered values
      escapeValue: false,
    },
    detection: {
      // Persist explicit user choice, fall back to browser language
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "loom:language",
    },
  });

export default i18n;
