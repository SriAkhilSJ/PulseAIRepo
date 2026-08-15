def test_generated_layoutprops_is_normalized(tmp_path):
    from src.tools.scaffold_tools import _normalize_generated_layout

    path = tmp_path / "src" / "app" / "layout.tsx"
    path.parent.mkdir(parents=True)
    path.write_text(
        'export default function RootLayout({ children }: LayoutProps<"/">) {\n'
        '  return <html><body>{children}</body></html>;\n}\n',
        encoding="utf-8",
    )
    assert _normalize_generated_layout(tmp_path) is True
    text = path.read_text(encoding="utf-8")
    assert 'LayoutProps' not in text
    assert '{ children: React.ReactNode }' in text
    assert _normalize_generated_layout(tmp_path) is False
