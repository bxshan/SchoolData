import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SchoolData — the US K-12 Wikipedia data desert",
  description:
    "Every US K-12 school (public + private) on one map. Red = no Wikipedia article yet. " +
    "An open dataset and call to action.",
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
