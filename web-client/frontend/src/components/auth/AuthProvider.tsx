import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { authApi } from "../../api/auth";
import { AUTH_REQUIRED_EVENT } from "../../api/client";
import { useT } from "../LanguageProvider";
import { LockedScreen } from "./LockedScreen";
import { LoginScreen } from "./LoginScreen";

type AuthState = "loading" | "locked" | "login" | "authenticated" | "error";

interface AuthContextValue {
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

/** Gate for the whole app: nothing below `children` mounts (so nothing
 * polls or fetches) until /auth/status reports an authenticated session. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const t = useT();
  const [state, setState] = useState<AuthState>("loading");
  const [expired, setExpired] = useState(false);

  const check = useCallback(async () => {
    setState("loading");
    try {
      const status = await authApi.status();
      if (!status.password_set) setState("locked");
      else setState(status.authenticated ? "authenticated" : "login");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => {
    function onAuthRequired() {
      setExpired(true);
      setState((current) => (current === "authenticated" ? "login" : current));
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    setExpired(false);
    setState("login");
  }, []);

  const value = useMemo(() => ({ logout }), [logout]);

  if (state === "authenticated") {
    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
  }
  if (state === "locked") return <LockedScreen onRetry={check} />;
  if (state === "error") {
    return <LockedScreen onRetry={check} errorMessage={t("auth.status_failed")} />;
  }
  if (state === "login") {
    return (
      <LoginScreen
        expired={expired}
        onAuthenticated={() => {
          setExpired(false);
          setState("authenticated");
        }}
      />
    );
  }
  return (
    <div className="flex h-dvh items-center justify-center bg-app text-sm text-fg-muted">
      {t("auth.loading")}
    </div>
  );
}
