import { createContext, useContext, useState, type ReactNode } from "react";

export type TimezonePreference = "UTC" | "local";

interface TimezoneContextValue {
  timezone: TimezonePreference;
  setTimezone: (tz: TimezonePreference) => void;
}

const TimezoneContext = createContext<TimezoneContextValue>({
  timezone: "local",
  setTimezone: () => {},
});

export function TimezoneProvider({ children }: { children: ReactNode }) {
  const [timezone, setTimezone] = useState<TimezonePreference>("local");

  return (
    <TimezoneContext.Provider value={{ timezone, setTimezone }}>
      {children}
    </TimezoneContext.Provider>
  );
}

export function useTimezone() {
  return useContext(TimezoneContext);
}
