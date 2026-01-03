import React from "react";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ error, errorInfo });
    console.error("Uncaught error:", error, errorInfo);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="min-h-screen bg-slate-50 p-6">
        <div className="mx-auto max-w-3xl rounded-2xl border border-rose-200 bg-white p-6 shadow-sm">
          <div className="text-sm font-medium text-rose-600">Application Error</div>
          <h1 className="mt-1 text-xl font-semibold text-slate-900">
            Something went wrong
          </h1>

          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs font-semibold text-slate-600 mb-1">Error</div>
            <div className="font-mono text-sm text-slate-900">
              {String(this.state.error || "")}
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 overflow-auto">
            <div className="text-xs font-semibold text-slate-600 mb-1">Component Stack</div>
            <pre className="text-xs text-slate-700 whitespace-pre-wrap">
              {this.state.errorInfo?.componentStack || ""}
            </pre>
          </div>

          <div className="mt-5 text-xs text-slate-500">
            Tip: open DevTools console for details.
          </div>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
