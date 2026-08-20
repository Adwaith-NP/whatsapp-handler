import { useEffect, useState } from "react";
import { getToken, clearToken, getMe } from "./api";
import { useRoute } from "./useRoute";
import Login from "./components/Login.jsx";
import UserMenu from "./components/UserMenu.jsx";
import {
  WhatsAppLogo,
  SettingsIcon,
  AutomationIcon,
  KeyIcon,
} from "./components/Icons.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import AutomationPage from "./pages/AutomationPage.jsx";
import ApiPage from "./pages/ApiPage.jsx";

const PRODUCT_NAME = "WhatsApp Handler";

// "/api-keys" rather than "/api": nginx proxies everything under /api/ to
// Django, so a page there would collide with the backend.
const PAGES = [
  { id: "settings", path: "/settings", label: "Settings", Icon: SettingsIcon, Page: SettingsPage },
  { id: "automation", path: "/automation", label: "Automation", Icon: AutomationIcon, Page: AutomationPage },
  { id: "api", path: "/api-keys", label: "API", Icon: KeyIcon, Page: ApiPage },
];
const HOME = PAGES[0];

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [user, setUser] = useState(null);
  const [path, navigate] = useRoute();

  // Also serves as a token check: a rejected call means the session is stale.
  useEffect(() => {
    if (!authed) {
      setUser(null);
      return;
    }
    let active = true;
    getMe()
      .then((u) => active && setUser(u))
      .catch(() => {
        if (!active) return;
        clearToken();
        setAuthed(false);
      });
    return () => {
      active = false;
    };
  }, [authed]);

  const active = PAGES.find((p) => p.path === path);

  // Unknown path (including "/") settles on the first page, without adding a
  // history entry you'd have to click back through.
  useEffect(() => {
    if (authed && !active) navigate(HOME.path, { replace: true });
  }, [authed, active, navigate]);

  function logout() {
    clearToken();
    setAuthed(false);
    navigate(HOME.path, { replace: true });
  }

  if (!authed) return <Login product={PRODUCT_NAME} onLogin={() => setAuthed(true)} />;

  const current = active || HOME;
  const Page = current.Page;

  return (
    <div className="app">
      <header className="topbar">
        <div className="product">
          <span className="product-mark">
            <WhatsAppLogo />
          </span>
          <span className="product-name">{PRODUCT_NAME}</span>
        </div>
        <UserMenu user={user} onLogout={logout} />
      </header>

      <div className="shell">
        <aside className="sidebar">
          <nav>
            {PAGES.map(({ id, path: to, label, Icon }) => (
              <button
                key={id}
                className={`nav-item${to === current.path ? " active" : ""}`}
                onClick={() => navigate(to)}
                aria-current={to === current.path ? "page" : undefined}
              >
                <span className="nav-icon">
                  <Icon />
                </span>
                {label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="content">
          <h1 className="page-title">{current.label}</h1>
          {/* Remounting on page change keeps each page's data fresh. */}
          <Page
            key={current.id}
            onNavigate={(id) =>
              navigate((PAGES.find((p) => p.id === id) || HOME).path)
            }
          />
        </main>
      </div>
    </div>
  );
}
