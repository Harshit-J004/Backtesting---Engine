import React, { useEffect, useState } from "react";
import ErrorBoundary from "./components/ErrorBoundary";
import HomePage from "./pages/HomePage";
import ResultsPage from "./pages/ResultsPage";
import { RunProvider } from "./state/RunContext";

function useHashRoute() {
  const getRoute = () => {
    const h = window.location.hash || "#/";
    if (h.startsWith("#/results")) return "results";
    return "home";
  };

  const [route, setRoute] = useState(getRoute);

  useEffect(() => {
    const onHashChange = () => setRoute(getRoute());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (to) => {
    window.location.hash = to === "results" ? "#/results" : "#/";
  };

  return { route, navigate };
}

export default function App() {
  const { route, navigate } = useHashRoute();

  return (
    <div className="min-h-screen w-full bg-gradient-to-b from-slate-50 via-white to-slate-50">
      <RunProvider navigate={navigate}>
        <ErrorBoundary>
          {/* top chrome */}
          <div className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/80 backdrop-blur">
            <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
              <div className="flex items-center gap-3">
                <div className="h-9 w-9 rounded-xl bg-slate-900 text-white grid place-items-center font-bold">
                  F
                </div>
                <div>
                  <div className="text-sm font-semibold text-slate-900">Felix</div>
                  <div className="text-xs text-slate-500">Backtesting & Strategy Analytics</div>
                </div>
              </div>

              <div className="text-xs text-slate-500">
                {route === "results" ? "Results" : "Workspace"}
              </div>
            </div>
          </div>

          <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
            {route === "results" ? <ResultsPage /> : <HomePage />}
          </div>
        </ErrorBoundary>
      </RunProvider>
    </div>
  );
}
