import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "TechnologyAgent · P02 本地模拟对话",
  description: "TechnologyAgent 采购 Agent 的本地工程底座、业务数据与 FakeAgent 对话",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
