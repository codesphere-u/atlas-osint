import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ATLAS OSINT", template: "%s · ATLAS OSINT" },
  description: "Open-source intelligence. Connected evidence. Verifiable insights.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#070b14", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
