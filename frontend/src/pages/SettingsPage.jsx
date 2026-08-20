import Connect from "../components/Connect.jsx";
import SendTest from "../components/SendTest.jsx";
import GeminiSettings from "../components/GeminiSettings.jsx";

export default function SettingsPage() {
  return (
    <>
      <Connect />
      <GeminiSettings />
      <SendTest />
    </>
  );
}
