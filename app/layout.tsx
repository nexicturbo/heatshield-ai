import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

function safeOrigin(rawHost: string | null, rawProtocol: string | null) {
  const host = rawHost?.split(",")[0]?.trim();
  const protocol = rawProtocol?.split(",")[0]?.trim();
  const safeHost = host && /^[a-z0-9.-]+(?::\d+)?$/i.test(host)
    ? host
    : "localhost:3000";
  const safeProtocol = protocol === "https" || protocol === "http"
    ? protocol
    : safeHost.startsWith("localhost")
      ? "http"
      : "https";

  return `${safeProtocol}://${safeHost}`;
}

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const origin = safeOrigin(
    requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host"),
    requestHeaders.get("x-forwarded-proto"),
  );
  const socialImage = new URL("/og.png", origin).toString();

  return {
    metadataBase: new URL(origin),
    title: {
      default: "HeatShield AI | Chicago heat-readiness planning",
      template: "%s | HeatShield AI",
    },
    description:
      "A transparent Chicago heat-readiness and cooling-access decision aid built from official public data.",
    applicationName: "HeatShield AI",
    keywords: [
      "Chicago heat",
      "cooling centers",
      "environmental forecasting",
      "public health preparedness",
      "accessible civic technology",
    ],
    authors: [{ name: "Henderson Mejia" }],
    creator: "Henderson Mejia",
    openGraph: {
      title: "HeatShield AI",
      description: "Know the heat. Find a cooler place. Make a plan.",
      type: "website",
      locale: "en_US",
      images: [{
        url: socialImage,
        alt: "HeatShield AI — Chicago heat-readiness and cooling-access planning",
      }],
    },
    twitter: {
      card: "summary_large_image",
      title: "HeatShield AI",
      description: "Know the heat. Find a cooler place. Make a plan.",
      images: [socialImage],
    },
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
