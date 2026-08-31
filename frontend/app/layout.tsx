import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "ReproForge — Turn agent failures into reproducible tests",
  description: "Gemini · TOON · Supabase Cloud · Next.js 15 · Rate Limited",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white antialiased">
        <header className="sticky top-0 z-40 border-b bg-white/80 backdrop-blur">
          <div className="mx-auto max-w-6xl flex h-14 items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2 font-bold">
              <span className="h-7 w-7 rounded bg-black text-white grid place-items-center text-xs">RF</span>
              ReproForge
              <span className="text-xs font-normal text-muted-foreground hidden sm:inline">Gemini · TOON · Supabase · Rate Limited</span>
            </Link>
            <nav className="flex items-center gap-2">
              <Link href="/" className="text-sm px-3 py-1.5 rounded hover:bg-secondary">Dashboard</Link>
              {}
              <a href="http://localhost:8000/docs" target="_blank" className="text-xs text-muted-foreground hover:underline">API Docs</a>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl p-4 md:p-6">{children}</main>
        <footer className="border-t mt-12 py-6 text-center text-xs text-muted-foreground">
          ReproForge — Turn agent failures into reproducible tests. Gemini 3.5 Flash → 2.5 Pro fallback · TOON · Supabase Cloud · Next.js 15 · Rate Limited
        </footer>
      </body>
    </html>
  );
}
