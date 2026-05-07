import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { EmptyState } from "../common/EmptyState";

const DashboardPage = lazy(() => import("../pages/DashboardPage"));
const ConnectorPage = lazy(() => import("../pages/ConnectorPage"));
const PublishPage = lazy(() => import("../pages/PublishPage"));
const VideosPage = lazy(() => import("../pages/VideosPage"));

export function AppRoutes() {
  return (
    <Suspense fallback={<EmptyState>Loading page…</EmptyState>}>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/connector" element={<ConnectorPage />} />
        <Route path="/publish" element={<PublishPage />} />
        <Route path="/videos" element={<VideosPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
