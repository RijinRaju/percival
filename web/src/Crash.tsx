import { Component, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

type State = { error: Error | null };

// Without this, any error thrown while rendering unmounts the whole app and
// leaves a blank page. This keeps the message on screen instead.
class Boundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error(error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <main className="mx-auto max-w-xl px-4 py-16 sm:px-8">
        <div className="label mb-2 border-b border-ink pb-2">something broke on this page</div>
        <p className="font-mono text-sm text-signal">▲ {error.message || String(error)}</p>
        <p className="mt-4 text-sm text-ink-2">
          Nothing was saved or changed. Go back, or reload. If it keeps happening, please open an issue with the
          message above.
        </p>
        <div className="mt-6 flex gap-4 font-mono text-sm">
          <button className="underline" onClick={() => window.history.back()}>
            go back
          </button>
          <button className="underline" onClick={() => window.location.reload()}>
            reload
          </button>
        </div>
      </main>
    );
  }
}

// a fresh boundary per route, so moving to another page clears the error
export function CrashGuard({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <Boundary key={pathname}>{children}</Boundary>;
}
