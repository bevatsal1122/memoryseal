import "./style.css";
import "./neobrutal.css";

export const metadata = {
  title: "MemorySeal — Memory protocol for multi-agent systems",
  description:
    "The memory protocol for multi-agent systems. Share agent context with scoped permissions, provenance, team access and client-encrypted vaults.",
};
export const viewport = { themeColor: "#f6f4eb" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
