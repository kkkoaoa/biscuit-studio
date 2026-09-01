/**
 * AuthProvider 是 SSO 相关的页面基建，不要删掉。
 * 业务代码写在 Outlet 里面（即各 page.tsx 中）。
 */
import { Outlet } from '@edenx/runtime/router';
import { AuthProvider } from '@/infra/sso/AuthProvider';
import '@/infra/sso/sso.css';
import './index.css';

export default function Layout() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}
