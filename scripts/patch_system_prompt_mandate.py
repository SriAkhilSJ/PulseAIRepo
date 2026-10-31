with open('PulseAIRepo/src/prompts/hermes/system_prompt.py', 'r', encoding='utf-8') as f:
    text = f.read()

mandate_def = '''
PRODUCTION_ENGINEERING_MANDATE = """# Production Engineering & Anti-Mock Mandate
When the user asks you to build an application, platform, startup venture, e-commerce store, SaaS, or complex system:
- **Respect Founder Emotion & High-Stakes Goals**: A non-technical user saying "for my startup" or "an Amazon for my business" is expressing an emotion, a dream, and a business commitment. Act like their 10x Principal CTO.
- **NEVER Downgrade to Static HTML/CSS Mocks**: Static single-file HTML/CSS/JS mockups without real data or backend functionality are FORBIDDEN for platform/startup requests.
- **Mandatory Production Architecture**:
  1. Relational database schema with real tables and persistence (e.g. SQLite / SQLAlchemy / Prisma).
  2. Runnable backend API routes with real validation and business logic.
  3. Interactive, reactive UI with live search, filters, state management, and shopping cart operations.
  4. Role separation: Customer Storefront + Admin / Vendor Hub.
  5. Automated verification: Run unit/integration tests and verify endpoints before declaring completion."""
'''

target = '''    platform_hint = resolve_platform_hint("", str(view.platform or ""), view.platform_hint_overrides)
    if platform_hint:
        stable_parts.append(platform_hint)'''

replacement = '''    platform_hint = resolve_platform_hint("", str(view.platform or ""), view.platform_hint_overrides)
    if platform_hint:
        stable_parts.append(platform_hint)

    # 8. Production engineering & anti-downgrade mandate
    if _has_tools(view):
        stable_parts.append(PRODUCTION_ENGINEERING_MANDATE)'''

if target in text and 'PRODUCTION_ENGINEERING_MANDATE' not in text:
    # insert mandate_def after imports
    idx = text.find('logger = logging.getLogger(__name__)')
    text = text[:idx] + mandate_def + '\n' + text[idx:]
    text = text.replace(target, replacement, 1)
    with open('PulseAIRepo/src/prompts/hermes/system_prompt.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("PATCH APPLIED SUCCESSFULLY to system_prompt.py")
else:
    print("TARGET NOT FOUND or ALREADY PATCHED in system_prompt.py")
