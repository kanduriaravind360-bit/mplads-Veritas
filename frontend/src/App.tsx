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
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={page(<CommandCentre />)} />
        <Route path="map" element={page(<RiskMap />)} />
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
          element={<RequireAuth roles={["MINISTRY", "STATE", "DISTRICT"]}>{page(<DataIngest />)}</RequireAuth>}
        />
        <Route path="*" element={<EmptyState title="Page not found" body="Use the sidebar or press Ctrl K to search." />} />
      </Route>
    </Routes>
  );
}
