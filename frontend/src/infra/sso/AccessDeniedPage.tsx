import { IconIllustrationCancel } from "@arco-design/iconbox-react-rdsvc";

export function AccessDeniedPage({ owner }: { owner: string }) {
  return (
    <div className="sso-access-denied" role="alert">
      <div className="sso-access-denied-content">
        <div className="sso-access-denied-icon">
          <IconIllustrationCancel />
        </div>
        <div className="sso-access-denied-title">您没有权限访问该页面</div>
        <div className="sso-access-denied-copy">
          请联系网页作者 {owner} 申请权限
        </div>
      </div>
    </div>
  );
}
