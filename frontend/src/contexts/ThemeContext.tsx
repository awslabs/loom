import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

export type Theme = "ayu" | "latte" | "dracula" | "everforest" | "ayudark" | "mocha" | "nord" | "rosepine" | "solarized" | "tokyonight";

export const THEME_LABELS: Record<Theme, string> = {
  ayu: "Ayu Light",
  latte: "Catppuccin Latte",
  everforest: "Everforest Light",
  rosepine: "Rosé Pine Dawn",
  solarized: "Solarized Light",
  ayudark: "Ayu Dark",
  mocha: "Catppuccin Mocha",
  dracula: "Dracula",
  nord: "Nord",
  tokyonight: "Tokyo Night",
};

const THEME_CLASSES: Record<Theme, string | null> = {
  ayu: "ayu",
  latte: null,
  dracula: "dracula",
  everforest: "everforest",
  ayudark: "ayudark",
  mocha: "dark",
  nord: "nord",
  rosepine: "rosepine",
  solarized: "solarized",
  tokyonight: "tokyonight",
};

export function isLightTheme(theme: Theme): boolean {
  return theme === "ayu" || theme === "latte" || theme === "rosepine" || theme === "everforest" || theme === "solarized";
}

interface ThemeContextValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "ayu",
  setTheme: () => {},
});

function detectInitialTheme(): Theme {
  const stored = localStorage.getItem("loom-theme") as Theme | null;
  if (stored && stored in THEME_CLASSES) return stored;
  const el = document.documentElement;
  if (el.classList.contains("ayu")) return "ayu";
  if (el.classList.contains("dark")) return "mocha";
  if (el.classList.contains("dracula")) return "dracula";
  if (el.classList.contains("everforest")) return "everforest";
  if (el.classList.contains("ayudark")) return "ayudark";
  if (el.classList.contains("nord")) return "nord";
  if (el.classList.contains("rosepine")) return "rosepine";
  if (el.classList.contains("solarized")) return "solarized";
  if (el.classList.contains("tokyonight")) return "tokyonight";
  return "ayu";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(detectInitialTheme);

  useEffect(() => {
    const el = document.documentElement;
    el.classList.remove("ayu", "dark", "dracula", "everforest", "ayudark", "nord", "rosepine", "solarized", "tokyonight");
    const cls = THEME_CLASSES[theme];
    if (cls) el.classList.add(cls);
    localStorage.setItem("loom-theme", theme);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme: setThemeState }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
