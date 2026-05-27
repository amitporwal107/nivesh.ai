import type { ISODate, Paise } from "./common";

export interface Goal {
  id: string;
  icon: string;                     // emoji or unicode glyph
  name: string;
  targetDate: ISODate;
  targetAmount: Paise;
  currentAmount: Paise;
  monthlySip: Paise;
  onTrack: boolean;
  progress: number;                 // 0..1
  message: string;                  // "Almost there!" / "Add ₹4k/mo"
}
