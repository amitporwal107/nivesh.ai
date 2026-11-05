/** Routes of the desk app (router basename /autodesk). Every screen renders inside the shell. */
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./shell/Shell";
import Phase2Screen from "./screens/Phase2";
import { Loading } from "./ui";

const Overview = lazy(() => import("./screens/Overview"));
const Agents = lazy(() => import("./screens/Agents"));
const Scanner = lazy(() => import("./screens/Scanner"));
const Approvals = lazy(() => import("./screens/Approvals"));
const Simulator = lazy(() => import("./screens/Simulator"));
const Policies = lazy(() => import("./screens/Policies"));

export default function App() {
  return (
    <Shell>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/scanner" element={<Scanner />} />
          <Route path="/workbench" element={<Phase2Screen id="workbench" />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/approvals/:approvalId" element={<Approvals />} />
          <Route path="/trades" element={<Phase2Screen id="trades" />} />
          <Route path="/pnl" element={<Phase2Screen id="pnl" />} />
          <Route path="/risk" element={<Phase2Screen id="risk" />} />
          <Route path="/middle" element={<Phase2Screen id="middle" />} />
          <Route path="/simulator" element={<Simulator />} />
          <Route path="/simulator/:simulationId" element={<Simulator />} />
          <Route path="/fleet" element={<Phase2Screen id="fleet" />} />
          <Route path="/policies" element={<Policies />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  );
}
