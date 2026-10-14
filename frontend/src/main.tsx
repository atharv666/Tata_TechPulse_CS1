import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Root element was not found.");
}

// The outer boundary guarantees the page is never left blank: any render error shows a message
// with a retry button instead.
createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary scope="the application">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
