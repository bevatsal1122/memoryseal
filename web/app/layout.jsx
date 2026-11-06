import "./style.css";
import "./neobrutal.css";

export const metadata = {
  title: "MemorySeal — Shared memory. Your rules.",
  description:
    "Manage agent memories, scoped permissions, team access and client-encrypted vaults in one connected workspace.",
};
export const viewport = { themeColor: "#f6f4eb" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
