import { createContext, useContext, useEffect, useState } from "react";
import { api, clearToken, getToken, setToken } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // 새로고침해도 로그인이 유지되도록 저장된 토큰으로 본인 확인을 한 번 한다.
  // 기기 승인이 취소됐으면 여기서 걸러진다.
  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        clearToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = (token, profile) => {
    setToken(token);
    setUser(profile);
  };

  const logout = () => {
    clearToken();
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, setUser, loading, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
