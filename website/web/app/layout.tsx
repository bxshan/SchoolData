import type { Metadata } from "next";
import "./globals.css";
import { SITE_URL } from "../lib/schools";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "SchoolData — a sourced record of every US K-12 school",
  description:
    "Every US K-12 school (public + private) on one map, with Wikipedia coverage by state and county. " +
    "Red = no Wikipedia article yet. An open, sourced dataset.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
