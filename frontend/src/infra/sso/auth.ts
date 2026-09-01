import { bytecloudAsyncJwtService } from '@bytecloud/common-lib';
import type { BytecloudJwtPartition } from '@bytecloud/common-lib/es/jwt/jwt.type';

export const JWT_HEADER = 'x-jwt-token';
export const CURRENT_USER_API_PATH = '/api/agents/v2/deployment/user';
export const ARTIFACT_SITE_AUTHORIZATION_CHECK_API_PATH =
  '/api/agents/v2/artifact_site/authorization/check';
export const DEFAULT_CURRENT_USER_API_HOST = 'aime.bytedance.net';

const USER_API_HOST_BY_APP_HOST_SUFFIX: Array<[string, string]> = [
  ['.aime-app.tiktok-row.net', 'aime.tiktok-row.net'],
];

type JwtService = Awaited<
  ReturnType<typeof bytecloudAsyncJwtService.getServiceByPartition>
>;

let authServicePromise: Promise<JwtService> | null = null;

function getPartition(): BytecloudJwtPartition {
  const partition = process.env.REACT_APP_PARTITION;

  if (!partition) {
    throw new Error(
      'REACT_APP_PARTITION is required to initialize SSO authentication.',
    );
  }

  return partition as BytecloudJwtPartition;
}

export function getAuthService(): Promise<JwtService> {
  if (!authServicePromise) {
    authServicePromise = bytecloudAsyncJwtService.getServiceByPartition(
      getPartition(),
    );
  }

  return authServicePromise;
}

export async function resolveJwt(forceRefresh = false): Promise<string> {
  const service = await getAuthService();

  if (forceRefresh) {
    service.clearCache();
  }

  return service.getJwt();
}

export async function redirectToSSO(): Promise<void> {
  const service = await getAuthService();
  service.redirectToLogin();
}

export async function fetchWithAuth(
  input: RequestInfo | URL,
  init: RequestInit = {},
  token?: string,
  redirectOnUnauthorized = true,
): Promise<Response> {
  const runRequest = async (forceRefresh = false) => {
    const jwt = token && !forceRefresh ? token : await resolveJwt(forceRefresh);
    const headers = new Headers(init.headers);
    headers.set(JWT_HEADER, jwt);

    return fetch(input, { ...init, headers });
  };

  let response = await runRequest();

  if (response.status === 401) {
    response = await runRequest(true).catch(() => response);
  }

  if (redirectOnUnauthorized && response.status === 401) {
    await redirectToSSO();
  }

  return response;
}

function getDeploymentApiHost(hostname: string): string {
  const matchedHost = USER_API_HOST_BY_APP_HOST_SUFFIX.find(([suffix]) =>
    hostname.endsWith(suffix),
  )?.[1];

  return matchedHost ?? DEFAULT_CURRENT_USER_API_HOST;
}

export function getCurrentUserApiUrl(
  hostname = window.location.hostname,
): string {
  return `https://${getDeploymentApiHost(hostname)}${CURRENT_USER_API_PATH}`;
}

export function getArtifactSiteAuthorizationCheckApiUrl(
  domain = window.location.origin,
  hostname = window.location.hostname,
): string {
  const url = new URL(
    `https://${getDeploymentApiHost(hostname)}${ARTIFACT_SITE_AUTHORIZATION_CHECK_API_PATH}`,
  );
  url.searchParams.set('domain', domain);
  return url.toString();
}

export type UserResponse = {
  id?: number;
  username: string;
  name: string;
  en_name?: string;
  avatar_url?: string;
  terminated?: boolean;
  lark_open_id?: string;
};

type CurrentUserErrorResponse = {
  code?: number;
  message?: string;
  data?: {
    owner?: unknown;
  };
};

export class AccessDeniedError extends Error {
  owner: string;

  constructor(owner: string) {
    super('Current user does not have permission to access this site.');
    this.name = 'AccessDeniedError';
    this.owner = owner;
  }
}

async function getAccessDeniedOwner(
  response: Response,
): Promise<string | null> {
  try {
    const body = (await response.json()) as CurrentUserErrorResponse;
    if (typeof body.data?.owner === 'string' && body.data.owner.trim()) {
      return body.data.owner;
    }
  } catch {
    // Ignore malformed error bodies and use the default owner label.
  }

  return null;
}

export async function checkArtifactSiteAuthorization(
  token: string,
): Promise<void> {
  const response = await fetchWithAuth(
    getArtifactSiteAuthorizationCheckApiUrl(),
    { headers: { Accept: 'application/json' } },
    token,
    false,
  );

  if (response.status === 401) {
    await redirectToSSO();
    throw new Error('站点权限接口认证失败');
  }

  if (response.status === 403) {
    const owner = await getAccessDeniedOwner(response);
    throw new AccessDeniedError(owner ?? '页面所有者');
  }

  if (!response.ok) {
    throw new Error(`站点权限接口请求失败（HTTP ${response.status}）`);
  }
}

export async function fetchCurrentUser(token: string): Promise<UserResponse> {
  const response = await fetchWithAuth(
    getCurrentUserApiUrl(),
    { headers: { Accept: 'application/json' } },
    token,
    false,
  );

  if (response.status === 401) {
    const owner = await getAccessDeniedOwner(response);
    if (owner) {
      throw new AccessDeniedError(owner);
    }
    await redirectToSSO();
    throw new Error('用户信息接口认证失败');
  }

  if (!response.ok) {
    throw new Error(`用户信息接口请求失败（HTTP ${response.status}）`);
  }

  const body = (await response.json()) as { user?: UserResponse };
  if (!body.user) {
    throw new Error('用户信息接口返回结构异常：缺少 user 字段');
  }
  return body.user;
}
