import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "TechnologyAgent · P00 工程底座",
  description: "TechnologyAgent 采购 Agent 的本地工程底座状态页",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
