import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <p className="p-6 font-mono">percival</p>
  </StrictMode>,
);
