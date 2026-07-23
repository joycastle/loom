import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { captureBootToken } from "@/lib/boot";
import { applyBootTheme } from "@/lib/theme";
import { applyBootLang } from "@/lib/lang";

// Grab (and hide) the sidecar's admin token, mark the surface, then resolve the
// boot theme + language onto <html> before anything renders — mirrors
// browse.html line 9.
captureBootToken();
applyBootTheme();
applyBootLang();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Top-level boundary: a crash in the runtime provider shows the error
        instead of a blank white screen. */}
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
