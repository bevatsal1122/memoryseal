import "./style.css";

export const metadata = { title: "MemorySeal", description: "Agent memory and authorization console" };

export default function RootLayout({ children }) {
  return <html lang="en"><body>{children}</body></html>;
}
