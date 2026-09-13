import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, getToken, setToken, UNAUTHORIZED_EVENT } from "@/lib/api";
import type { Role, User } from "@/lib/types";

const USER_KEY = "sentinel.user";

interface AuthState {
  user: User | null;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
  can: (...roles: Role[]) => boolean;
  isReviewer: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

function storedUser(): User | null {
  try {
    const text = localStorage.getItem(USER_KEY);
    return text && getToken() ? (JSON.parse(text) as User) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(storedUser);
  const client = useQueryClient();

  const logout = useCallback(() => {
    setToken(null);
    try {
      localStorage.removeItem(USER_KEY);
    } catch {
      /* ignore */
    }
    setUser(null);
    client.clear();
  }, [client]);

  useEffect(() => {
    window.addEventListener(UNAUTHORIZED_EVENT, logout);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, logout);
  }, [logout]);

  const login = useCallback(
    async (email: string, password: string) => {
      const response = await api<{ access_token: string; user: User }>("/auth/login", {
        body: { email, password },
      });
      client.clear();
      setToken(response.access_token);
      try {
        localStorage.setItem(USER_KEY, JSON.stringify(response.user));
      } catch {
        /* ignore */
      }
      setUser(response.user);
      return response.user;
    },
    [client],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      login,
      logout,
      can: (...roles) => !!user && roles.includes(user.role),
      isReviewer: !!user && user.role !== "MP",
    }),
    [user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}
