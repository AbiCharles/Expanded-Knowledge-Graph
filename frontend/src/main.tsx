import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// Minimal error boundary so a render crash inside the app doesn't blank
// the whole page — surfaces the error message + stack and a reload
// button. Without this, an uncaught throw in any component unmounts
// the React tree and the user sees a white screen with no diagnostic.
class AppErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[AppErrorBoundary]", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: 24,
            fontFamily: "system-ui, sans-serif",
            color: "#0f172a",
            background: "#fef2f2",
            borderLeft: "4px solid #dc2626",
            margin: 20,
            borderRadius: 6,
          }}
        >
          <h1 style={{ marginTop: 0, fontSize: 18 }}>
            ⚠ Render error — the UI crashed
          </h1>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              background: "#fff",
              padding: 12,
              borderRadius: 4,
              fontSize: 12,
              overflow: "auto",
              maxHeight: 320,
            }}
          >
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
          <button
            type="button"
            onClick={() => location.reload()}
            style={{
              padding: "8px 14px",
              background: "#0f172a",
              color: "#fff",
              border: 0,
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>
);
