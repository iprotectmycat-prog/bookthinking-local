import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import "./globals.css";
import "./reading-responsive.css";

export const metadata: Metadata = {
  title: "BookThinking",
  description: "本机运行的证据优先书籍学习工具",
};

export const viewport: Viewport = { viewportFit: "cover" };

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
