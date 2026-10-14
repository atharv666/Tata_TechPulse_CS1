import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Shown above the message, e.g. the screen name. */
  scope?: string;
}

interface State {
  error?: Error;
}

/**
 * A render error must never blank the whole page. This shows what happened and lets the person try
 * again without reloading (give it a ``key`` that changes with the screen so it resets on navigation).
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = {};

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error", this.props.scope ?? "", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="state state-error crash-panel" role="alert">
        <h3>Something went wrong{this.props.scope ? ` in ${this.props.scope}` : ""}</h3>
        <p>{this.state.error.message || "An unexpected error occurred."}</p>
        <div className="action-buttons">
          <button onClick={() => this.setState({ error: undefined })}>Try again</button>
          <button className="btn-secondary" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </div>
      </div>
    );
  }
}
