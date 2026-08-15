export type Theme = {
  key: string;
  label: string;
  subtitle: string;
  ctaPrimary: string;
  ctaSecondary: string;
  palette: {
    base: string;
    text: string;
    accent: string;
    overlay: string;
  };
  video: string;
  poster: string;
};

export const themes: Theme[] = [
  {
    key: "nature",
    label: "Immersion",
    subtitle: "Forests and tides in motion.",
    ctaPrimary: "Explore",
    ctaSecondary: "Learn more",
    palette: {
      base: "bg-stone-950",
      text: "text-stone-100",
      accent: "text-emerald-400",
      overlay: "bg-stone-900/60",
    },
    video:
      "/videos/video-d.mp4",
    poster:
      "https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1920&q=80",
  },
  {
    key: "still-life",
    label: "Still Life",
    subtitle: "Ceramics and glassware, held in light.",
    ctaPrimary: "Discover",
    ctaSecondary: "View collection",
    palette: {
      base: "bg-neutral-950",
      text: "text-neutral-100",
      accent: "text-amber-300",
      overlay: "bg-neutral-900/50",
    },
    video:
      "/videos/video-b.mp4",
    poster:
      "https://images.unsplash.com/photo-1513364776144-60967b0f800f?auto=format&fit=crop&w=1920&q=80",
  },
  {
    key: "materials",
    label: "Materials",
    subtitle: "Leather and fabric, touched by time.",
    ctaPrimary: "Experience",
    ctaSecondary: "Read story",
    palette: {
      base: "bg-stone-950",
      text: "text-stone-100",
      accent: "text-rose-400",
      overlay: "bg-stone-900/55",
    },
    video:
      "/videos/video-c.mp4",
    poster:
      "https://images.unsplash.com/photo-1558171813-4c088753af8f?auto=format&fit=crop&w=1920&q=80",
  },
  {
    key: "metal-parts",
    label: "Metal Parts",
    subtitle: "Cinematic gears and machined surfaces.",
    ctaPrimary: "Watch",
    ctaSecondary: "See details",
    palette: {
      base: "bg-zinc-950",
      text: "text-zinc-100",
      accent: "text-cyan-400",
      overlay: "bg-zinc-900/60",
    },
    video:
      "/videos/video-a.mp4",
    poster:
      "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1920&q=80",
  },
];

export function getTheme(key: string): Theme | undefined {
  return themes.find((t) => t.key === key);
}
