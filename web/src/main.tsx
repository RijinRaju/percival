import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { CrashGuard } from "./Crash";
import { SessionProvider } from "./session";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <CrashGuard>
        <SessionProvider>
          <App />
        </SessionProvider>
      </CrashGuard>
    </BrowserRouter>
  </StrictMode>,
);
