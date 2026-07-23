import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[loom-chat-ui]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="loom-error">
          <strong>界面渲染出错</strong>
          <p>{this.state.error.message}</p>
          <button type="button" className="loom-btn" onClick={() => this.setState({ error: null })}>
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
