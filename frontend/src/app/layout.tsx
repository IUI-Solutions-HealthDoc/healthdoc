import type { Metadata } from "next";
import { headers } from "next/headers";
import { fontVariables } from "@/styles/fonts";
import { Providers } from "@/components/providers";
import MainLayout from "@/components/common/MainLayout";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "HealthDoc HMIS",
  description: "Hospital Information Management System",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Read the per-request nonce set by `proxy.ts` so Next stamps framework
  // scripts and this layout stays dynamic (nonces cannot be statically cached).
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <html lang="en" className={fontVariables}>
      <body>
        <Providers nonce={nonce}>
          <MainLayout>{children}</MainLayout>
        </Providers>
      </body>
    </html>
  );
}
