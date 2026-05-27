import { jsx as _jsx } from "react/jsx-runtime";
import { Badge } from "@/components/ui/badge";
const LABEL = {
    keep: "KEEP",
    reduce: "REDUCE",
    add: "ADD",
};
const TONE = {
    keep: "good",
    reduce: "neg",
    add: "warm",
};
export function StatusBadge({ action }) {
    return _jsx(Badge, { tone: TONE[action], children: LABEL[action] });
}
