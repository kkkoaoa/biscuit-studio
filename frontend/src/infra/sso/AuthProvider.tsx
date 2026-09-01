import {
  createContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { AccessDeniedPage } from './AccessDeniedPage';
import {
  AccessDeniedError,
  checkArtifactSiteAuthorization,
  fetchCurrentUser,
  getAuthService,
  redirectToSSO,
  resolveJwt,
  type UserResponse,
} from './auth';

export type AuthContextValue = {
  user: UserResponse | null;
  token: string | null;
  isLoading: boolean;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [accessDeniedOwner, setAccessDeniedOwner] = useState<string | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;

    const initAuth = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const isSsoCallback = urlParams.get('auth_callback') === 'true';

      try {
        const service = await getAuthService();
        const jwt = await service.getJwt();

        if (!jwt) {
          if (isSsoCallback) {
            console.error('Unable to get a JWT after returning from SSO.');
            if (!cancelled) {
              setAccessDeniedOwner('页面所有者');
              setIsLoading(false);
            }
          } else {
            await redirectToSSO();
          }
          return;
        }

        if (!cancelled) {
          setToken(jwt);
        }

        if (isSsoCallback) {
          urlParams.delete('auth_callback');
          const search = urlParams.toString();
          window.history.replaceState(
            {},
            document.title,
            `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`,
          );
        }

        try {
          await checkArtifactSiteAuthorization(jwt);
          const currentUser = await fetchCurrentUser(jwt);
          const currentJwt = await resolveJwt();
          if (!cancelled) {
            setUser(currentUser);
            setToken(currentJwt);
            setLoadError(false);
            setAccessDeniedOwner(null);
            setIsLoading(false);
          }
        } catch (error) {
          if (error instanceof AccessDeniedError) {
            if (!cancelled) {
              setAccessDeniedOwner(error.owner);
              setIsLoading(false);
            }
            return;
          }

          if (!cancelled) {
            setLoadError(true);
            setIsLoading(false);
          }
          console.error('Unable to load the signed-in user:', error);
        }
      } catch (error) {
        console.error('Unable to initialize SSO authentication:', error);
        if (!isSsoCallback) {
          try {
            await redirectToSSO();
          } catch (redirectError) {
            console.error('Unable to redirect to SSO:', redirectError);
            if (!cancelled) {
              setAccessDeniedOwner('页面所有者');
              setIsLoading(false);
            }
          }
        } else if (!cancelled) {
          setAccessDeniedOwner('页面所有者');
          setIsLoading(false);
        }
      }
    };

    void initAuth();

    return () => {
      cancelled = true;
    };
  }, []);


  const logout = async () => {
    try {
      const service = await getAuthService();
      await service.logout();
      setUser(null);
      setToken(null);
      setLoadError(false);
      setAccessDeniedOwner(null);
    } catch (error) {
      console.error('Unable to log out:', error);
    }
  };

  if (isLoading) {
    return null;
  }

  if (accessDeniedOwner) {
    return <AccessDeniedPage owner={accessDeniedOwner} />;
  }

  if (loadError) {
    return (
      <div className="sso-access-denied" role="alert">
        页面加载失败，请刷新重试
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, token, isLoading, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
