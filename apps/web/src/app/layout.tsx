import type { Metadata, Viewport } from "next";

import { Shell } from "@/components/shell";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "ATLAS - Search Intelligence & Content Ops", template: "%s · ATLAS" },
  description: "Autonomous Search Intelligence & Content Operations - technical demonstration",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0b1020" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
