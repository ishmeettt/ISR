import { useState } from "react";
import splash from "./assets/splash.jpg";
import { Me } from "./api";
import Login from "./Login";

export default function Welcome({ onDone }: { onDone: (me: Me) => void }) {
  const [showLogin, setShowLogin] = useState(false);

  if (!showLogin) {
    return (
      <div className="welcome" style={{ backgroundImage: `url(${splash})` }}>
        <div className="welcome-actions">
          <button className="btn-primary" onClick={() => setShowLogin(true)}>
            Log in
          </button>
          <button className="btn-ghost" onClick={() => setShowLogin(true)}>
            Sign up
          </button>
        </div>
        <p className="welcome-tagline">RUN → JUDGE → VERIFY → EXPLAIN</p>
      </div>
    );
  }

  return (
    <div className="welcome" style={{ backgroundImage: `url(${splash})` }}>
      <div className="welcome-panel">
        <button className="welcome-back" onClick={() => setShowLogin(false)} aria-label="Back">
          ← Back
        </button>
        <Login onDone={onDone} />
      </div>
    </div>
  );
}
