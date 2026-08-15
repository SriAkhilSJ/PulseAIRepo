import { notFound } from "next/navigation";
import VideoHero from "@/components/VideoHero";
import { getTheme } from "@/lib/themes";

export default async function ThemePage({
  params,
}: {
  params: Promise<{ theme: string }>;
}) {
  const { theme } = await params;
  const resolved = getTheme(theme);

  if (!resolved) {
    notFound();
  }

  return <VideoHero themeKey={resolved.key} />;
}
