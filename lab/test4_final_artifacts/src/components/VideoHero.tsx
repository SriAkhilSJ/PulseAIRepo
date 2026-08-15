"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { themes, type Theme } from "@/lib/themes";

const titles: Record<string, [string, string]> = {
  nature: ["Living", "Landscapes"],
  "still-life": ["Quiet", "Objects"],
  materials: ["Tactile", "Surfaces"],
  "metal-parts": ["Machined", "Motion"],
};

export default function VideoHero({ themeKey }: { themeKey: string }) {
  const theme = themes.find((item) => item.key === themeKey) as Theme;
  const videoRef = useRef<HTMLVideoElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (reducedMotion) videoRef.current?.pause();
    else videoRef.current?.play().catch(() => undefined);
  }, [reducedMotion]);

  const [lineOne, lineTwo] = titles[theme.key];

  return (
    <main
      className={`relative isolate min-h-screen overflow-hidden ${theme.palette.base} ${theme.palette.text}`}
      style={{ backgroundImage: `url(${theme.poster})`, backgroundPosition: "center", backgroundSize: "cover" }}
    >
      <video
        ref={videoRef}
        autoPlay
        muted
        loop
        playsInline
        preload="metadata"
        poster={theme.poster}
        aria-label={`${theme.label} atmospheric background film`}
        onLoadedData={() => setLoaded(true)}
        onCanPlay={() => setLoaded(true)}
        className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-1000 ${loaded ? "opacity-100" : "opacity-0"}`}
      >
        <source src={theme.video} type="video/mp4" />
      </video>

      <div className="absolute inset-0 bg-gradient-to-b from-black/50 via-black/10 to-black/75" />
      <div className={`absolute inset-0 mix-blend-multiply ${theme.palette.overlay}`} />
      <div className="hero-grain absolute inset-0 opacity-25" aria-hidden="true" />

      <div className="relative z-10 flex min-h-screen flex-col px-6 py-6 sm:px-10 lg:px-14 lg:py-9">
        <header className="flex items-center justify-between border-b border-white/20 pb-5">
          <Link href="/" className="text-sm font-semibold uppercase tracking-[0.3em] text-white">
            Form / Motion
          </Link>
          <nav aria-label="Showcase themes" className="hidden items-center gap-7 md:flex">
            {themes.map((item) => (
              <Link
                key={item.key}
                href={`/${item.key}`}
                aria-current={item.key === theme.key ? "page" : undefined}
                className={`text-[11px] uppercase tracking-[0.18em] transition ${item.key === theme.key ? "text-white" : "text-white/55 hover:text-white"}`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <span className="rounded-full border border-white/30 px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-white/80">
            Film 0{themes.findIndex((item) => item.key === theme.key) + 1}
          </span>
        </header>

        <section className="mt-auto grid items-end gap-10 pb-3 pt-28 lg:grid-cols-[1fr_280px]">
          <div>
            <div className="mb-6 flex items-center gap-3">
              <span className="h-px w-10 bg-current opacity-70" />
              <span className={`text-[11px] font-medium uppercase tracking-[0.32em] ${theme.palette.accent}`}>
                {theme.label} / Material study
              </span>
            </div>
            <h1 className="max-w-5xl text-[clamp(4rem,12vw,10rem)] font-light leading-[0.72] tracking-[-0.065em] text-white">
              <span className="block">{lineOne}</span>
              <span className="ml-[0.34em] block italic text-white/90">{lineTwo}</span>
            </h1>
          </div>

          <aside className="border-l border-white/25 pl-6 text-white">
            <p className="text-sm leading-6 text-white/70">{theme.subtitle}</p>
            <div className="mt-7 flex flex-col gap-3">
              <button className="group flex items-center justify-between border border-white bg-white px-5 py-3 text-xs font-semibold uppercase tracking-[0.17em] text-black transition hover:bg-transparent hover:text-white">
                {theme.ctaPrimary}<span aria-hidden="true">↗</span>
              </button>
              <button className="flex items-center justify-between border-b border-white/40 px-1 py-3 text-left text-xs uppercase tracking-[0.17em] text-white/85 transition hover:border-white">
                {theme.ctaSecondary}<span aria-hidden="true">01:24</span>
              </button>
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
