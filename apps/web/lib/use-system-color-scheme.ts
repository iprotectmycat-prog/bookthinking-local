"use client";

import { useEffect, useState } from "react";

export type SystemColorScheme = "light" | "dark";

const darkSchemeQuery = "(prefers-color-scheme: dark)";

function readSystemColorScheme(): SystemColorScheme {
  return typeof window !== "undefined" && window.matchMedia?.(darkSchemeQuery).matches
    ? "dark"
    : "light";
}

export function useSystemColorScheme(): SystemColorScheme {
  const [colorScheme, setColorScheme] = useState<SystemColorScheme>(readSystemColorScheme);

  useEffect(() => {
    if (!window.matchMedia) {
      return;
    }

    const mediaQuery = window.matchMedia(darkSchemeQuery);
    const updateColorScheme = () => setColorScheme(mediaQuery.matches ? "dark" : "light");

    updateColorScheme();
    mediaQuery.addEventListener("change", updateColorScheme);
    return () => mediaQuery.removeEventListener("change", updateColorScheme);
  }, []);

  return colorScheme;
}
