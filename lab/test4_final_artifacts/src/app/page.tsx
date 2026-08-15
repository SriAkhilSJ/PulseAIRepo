import Link from "next/link";
import { themes } from "@/lib/themes";

export default function IndexPage() {
  return (
    <div className="min-h-screen bg-stone-950">
      <header className="border-b border-stone-800">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <Link href="/" className="text-stone-100 tracking-tight">
            Pulse
          </Link>
          <nav className="flex items-center gap-6 text-sm tracking-wide text-stone-400">
            {themes.map((t) => (
              <Link
                key={t.key}
                href={`/${t.key}`}
                className="hover:text-stone-100 transition-colors"
              >
                {t.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-20">
        <div className="mb-12 text-center">
          <h1 className="text-4xl md:text-6xl font-light tracking-tight text-stone-100">
            Video Hero
          </h1>
          <p className="mt-4 max-w-xl mx-auto text-stone-400">
            Four curated routes. Each with its own palette, texture, and motion.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {themes.map((t) => (
            <Link
              key={t.key}
              href={`/${t.key}`}
              className="group block rounded-sm border border-stone-800 bg-stone-900/40 p-6 hover:border-stone-700 hover:bg-stone-900/60 transition-all"
            >
              <div
                className="mb-4 aspect-video rounded-sm overflow-hidden"
                style={{
                  backgroundImage: `url(${t.poster})`,
                  backgroundSize: "cover",
                  backgroundPosition: "center",
                }}
              >
                <div className="absolute inset-0 bg-stone-900/30" />
              </div>
              <span className="mb-2 block text-xs tracking-[0.2em] uppercase text-emerald-400">
                {t.label}
              </span>
              <h3 className="text-lg font-light text-stone-100">
                {t.label === "Metal Parts"
                  ? "Machined Motion"
                  : t.label === "Still Life"
                  ? "Quiet Objects"
                  : t.label === "Materials"
                  ? "Tactile Surfaces"
                  : "Living Landscapes"}
              </h3>
              <p className="mt-1 text-sm text-stone-400">{t.subtitle}</p>
            </Link>
          ))}
        </div>
      </main>

      <footer className="border-t border-stone-800">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
          <span className="text-xs text-stone-500">© {new Date().getFullYear()} Pulse</span>
          <span className="text-xs text-stone-500">All rights reserved.</span>
        </div>
      </footer>
    </div>
  );
}
