import { api } from "./client";

export interface AuthStatus {
  authenticated: boolean;
  password_set: boolean;
}

export const authApi = {
  status: () => api.get<AuthStatus>("/auth/status"),
  login: (password: string) => api.post<{ authenticated: true }>("/auth/login", { password }),
  logout: () => api.post<{ authenticated: false }>("/auth/logout", {}),
  changePassword: (current: string, next: string) =>
    api.post<{ ok: true }>("/auth/password", { current, new: next }),
};
