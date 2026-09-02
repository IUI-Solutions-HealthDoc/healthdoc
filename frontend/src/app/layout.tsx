import type { Metadata } from "next";
import { fontVariables } from "@/styles/fonts";
import { Providers } from "@/components/providers";
import MainLayout from "@/components/common/MainLayout";
import "@/styles/globals.css";

/**
 * Every route renders per request (WASA M3).
 *
 * Not a performance choice — a correctness one for the CSP nonce. The nonce in
 * src/proxy.ts is minted per request, and Next can only stamp it onto its inline
 * bootstrap while it is actually rendering. Statically prerendered HTML is built
 * once, long before any nonce exists, so it ships with bare <script> tags: the
 * policy then blocks Next's own hydration payload and every screen renders as a
 * blank page. Verified by building without this line and diffing the served HTML
 * against the header — 2 inline scripts, 0 nonces.
 *
 * The cost is small here because it is only the shell that goes dynamic: every
 * page under this layout is a client component that fetches through the
 * authenticated API, so nothing user-visible was ever being cached.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "HealthDoc HMIS",
  description: "Hospital Information Management System",
  applicationName: "HealthDoc HMIS",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/healthdoc-logo.png",
    shortcut: "/healthdoc-logo.png",
    apple: "/healthdoc-logo.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={fontVariables}>
      <body>
        <Providers>
          <MainLayout>{children}</MainLayout>
        </Providers>
      </body>
    </html>
  );
}
