import React, { createContext, useContext, useState } from "react";

const NumberFormatContext = createContext(null);
export const useNumberFormat = () => useContext(NumberFormatContext);

export const fmt = (val, mode = "auto") => {
  const abs = Math.abs(val);
  if (mode === "cr" || (mode === "auto" && abs >= 10000000)) return `₹${(val / 10000000).toFixed(2)} Cr`;
  if (mode === "l" || (mode === "auto" && abs >= 100000)) return `₹${(val / 100000).toFixed(2)} L`;
  if (abs >= 1000) return `₹${(val / 1000).toFixed(1)}K`;
  return `₹${val.toFixed(0)}`;
};

export const fmtShort = (val, mode = "auto") => {
  const abs = Math.abs(val);
  if (mode === "cr" || (mode === "auto" && abs >= 10000000)) return `${(val / 10000000).toFixed(1)}Cr`;
  if (mode === "l" || (mode === "auto" && abs >= 100000)) return `${(val / 100000).toFixed(1)}L`;
  if (abs >= 1000) return `${(val / 1000).toFixed(0)}K`;
  return `${val.toFixed(0)}`;
};

export const NumberFormatProvider = ({ children }) => {
  const [displayMode, setDisplayMode] = useState("auto"); // "auto" | "l" | "cr"
  const f = (val) => fmt(val, displayMode);
  const fs = (val) => fmtShort(val, displayMode);
  return (
    <NumberFormatContext.Provider value={{ displayMode, setDisplayMode, fmt: f, fmtShort: fs }}>
      {children}
    </NumberFormatContext.Provider>
  );
};
