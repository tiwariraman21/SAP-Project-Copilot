import type { Metadata } from "next";
import "./globals.css";
import "./overview.css";
import "./artifacts.css";
import "./brand.css";
export const metadata: Metadata = { title: "InfraBeat | SAP Project Copilot", description: "InfraBeat requirement intelligence for SAP delivery" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
