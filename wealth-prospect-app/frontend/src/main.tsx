import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Shell from "./components/Shell";
import { PersonaProvider } from "./lib/persona";
import Dashboard from "./pages/Dashboard";
import Prospects from "./pages/Prospects";
import ProspectDetailPage from "./pages/ProspectDetail";
import Lists from "./pages/Lists";
import ImportPage from "./pages/Import";
import Sources from "./pages/Sources";
import Compliance from "./pages/Compliance";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1 } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <PersonaProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<Dashboard />} />
              <Route path="prospects" element={<Prospects />} />
              <Route path="prospects/:id" element={<ProspectDetailPage />} />
              <Route path="lists" element={<Lists />} />
              <Route path="lists/:id" element={<Lists />} />
              <Route path="import" element={<ImportPage />} />
              <Route path="sources" element={<Sources />} />
              <Route path="compliance" element={<Compliance />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PersonaProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
