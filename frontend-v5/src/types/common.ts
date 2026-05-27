/** Currency in paise to avoid float drift. UI displays as ₹. */
export type Paise = number;

export type ISODate = string;            // "2026-05-27"
export type ISOTimestamp = string;       // "2026-05-27T09:41:00+05:30"

export type AsyncStatus = "idle" | "loading" | "success" | "error";

export type Severity = "info" | "watch" | "fix" | "good";

export interface Pagination {
  page: number;
  pageSize: number;
  total: number;
}

export interface ApiEnvelope<T> {
  data: T;
  generatedAt: ISOTimestamp;
}
