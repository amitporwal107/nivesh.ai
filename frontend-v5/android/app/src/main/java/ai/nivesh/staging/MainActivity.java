package ai.nivesh.staging;

import android.webkit.CookieManager;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onStart() {
        super.onStart();
        // The app's WebView runs at https://localhost, but the API session
        // cookie belongs to staging.niveshcopilot.com — a third-party cookie,
        // which Android WebView blocks by default. Without this, login succeeds
        // (/api/auth/google sets the cookie) but the very next request
        // (/api/auth/me) sends no cookie, so RequireAuth bounces back to /login.
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        if (getBridge() != null && getBridge().getWebView() != null) {
            cookieManager.setAcceptThirdPartyCookies(getBridge().getWebView(), true);
        }
    }
}
