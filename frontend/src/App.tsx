import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, ApiError } from "./lib/api";
import type { CurrentUser } from "./lib/types";
import { Shell } from "./components/layout/Shell";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { TenantFormPage } from "./pages/TenantFormPage";
import { TenantConfigPage } from "./pages/TenantConfigPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunHistoryPage } from "./pages/RunHistoryPage";
import { BackfillJobPage } from "./pages/BackfillJobPage";
import { ChatPage } from "./pages/ChatPage";

function useCurrentUser() {
  return useQuery<CurrentUser, ApiError>({
    queryKey: ["currentUser"],
    queryFn: api.me,
    retry: false,
    staleTime: 30_000,
  });
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  const { data, isLoading, isError, error } = useCurrentUser();
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (isError && (error.status === 401 || error.status === 403)) {
    return <Navigate to="/login" replace state={{ from: loc }} />;
  }
  if (!data) {
    return <Navigate to="/login" replace />;
  }
  return <Shell user={data}>{children}</Shell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route
        path="/tenants/new"
        element={
          <RequireAuth>
            <TenantFormPage mode="create" />
          </RequireAuth>
        }
      />
      <Route
        path="/tenants/:tenantId/edit"
        element={
          <RequireAuth>
            <TenantFormPage mode="edit" />
          </RequireAuth>
        }
      />
      <Route
        path="/tenants/:tenantId/config"
        element={
          <RequireAuth>
            <TenantConfigPage />
          </RequireAuth>
        }
      />
      <Route
        path="/runs"
        element={
          <RequireAuth>
            <RunHistoryPage />
          </RequireAuth>
        }
      />
      <Route
        path="/runs/:runId"
        element={
          <RequireAuth>
            <RunDetailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/backfill/:jobId"
        element={
          <RequireAuth>
            <BackfillJobPage />
          </RequireAuth>
        }
      />
      <Route
        path="/tenants/:tenantId/chat"
        element={
          <RequireAuth>
            <ChatPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
