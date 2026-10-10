import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./styles.css";
import App from "./App";
import { ToastProvider } from "./state/Toasts";
import { BoardProvider } from "./state/BoardContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <BoardProvider>
        <App />
      </BoardProvider>
    </ToastProvider>
  </StrictMode>,
);
