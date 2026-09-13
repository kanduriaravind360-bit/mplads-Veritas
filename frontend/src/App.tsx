import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { EmptyState, PanelSkeleton } from "@/components/common";
import LoginPage from "@/pages/Login";

const CommandCentre = lazy(() => import("@/pages/CommandCentre"));
const RiskMap = lazy(() => import("@/pages/RiskMap"));
const AlertsInbox = lazy(() => import("@/pages/AlertsInbox"));
const WorkDetail = lazy(() => import("@/pages/WorkDetail"));
const DuplicateFinder = lazy(() => import("@/pages/DuplicateFinder"));
const VendorNetwork = lazy(() => import("@/pages/VendorNetwork"));
const Delays = lazy(() => import("@/pages/Delays"));
const Compliance = lazy(() => import("@/pages/Compliance"));
const Trends = lazy(() => import("@/pages/Trends"));
const Portfolio = lazy(() => import("@/pages/Portfolio"));
const ModelPerformance = lazy(() => import("@/pages/ModelPerformance"));
const DataIngest = lazy(() => import("@/pages/DataIngest"));
const Cases = lazy(() => import("@/pages/Cases"));
const MoneyAtRisk = lazy(() => import("@/pages/MoneyAtRisk"));
const Simulator = lazy(() => import("@/pages/Simulator"));
const Learning = lazy(() => import("@/pages/Learning"));
const CitizenView = lazy(() => import("@/pages/CitizenView"));

const REVIEWERS: Role[] = ["MINISTRY", "STATE", "DISTRICT"];

function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

const page = (node: ReactNode) => <Suspense fallback={<PanelSkeleton rows={8} />}>{node}</Suspense>;

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/public" element={page(<CitizenView />)} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={page(<CommandCentre />)} />
        <Route path="map" element={page(<RiskMap />)} />
        <Route path="money" element={page(<MoneyAtRisk />)} />
        <Route path="cases" element={<RequireAuth roles={REVIEWERS}>{page(<Cases />)}</RequireAuth>} />
        <Route path="simulator" element={<RequireAuth roles={REVIEWERS}>{page(<Simulator />)}</RequireAuth>} />
        <Route path="learning" element={<RequireAuth roles={REVIEWERS}>{page(<Learning />)}</RequireAuth>} />
        <Route path="alerts" element={page(<AlertsInbox />)} />
        <Route path="works/*" element={page(<WorkDetail />)} />
        <Route path="duplicates" element={page(<DuplicateFinder />)} />
        <Route path="network" element={page(<VendorNetwork />)} />
        <Route path="delays" element={page(<Delays />)} />
        <Route path="compliance" element={page(<Compliance />)} />
        <Route path="trends" element={page(<Trends />)} />
        <Route path="portfolio" element={page(<Portfolio />)} />
        <Route path="models" element={page(<ModelPerformance />)} />
        <Route
          path="ingest"
          element={<RequireAuth roles={REVIEWERS}>{page(<DataIngest />)}</RequireAuth>}
        />
        <Route path="*" element={<EmptyState title="Page not found" body="Use the sidebar or press Ctrl K to search." />} />
      </Route>
    </Routes>
  );
}
