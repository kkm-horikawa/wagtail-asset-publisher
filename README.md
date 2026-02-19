# wagtail-asset-publisher

[![PyPI version](https://badge.fury.io/py/wagtail-asset-publisher.svg)](https://badge.fury.io/py/wagtail-asset-publisher)
[![Downloads](https://static.pepy.tech/badge/wagtail-asset-publisher)](https://pepy.tech/project/wagtail-asset-publisher)
[![Published on Django Packages](https://img.shields.io/badge/Published%20on-Django%20Packages-0c3c26)](https://djangopackages.org/packages/p/wagtail-asset-publisher/)
[![CI](https://github.com/kkm-horikawa/wagtail-asset-publisher/actions/workflows/ci.yml/badge.svg)](https://github.com/kkm-horikawa/wagtail-asset-publisher/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/kkm-horikawa/wagtail-asset-publisher/branch/develop/graph/badge.svg)](https://codecov.io/gh/kkm-horikawa/wagtail-asset-publisher)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

Automatically extract, build, and publish page-level CSS/JS assets from Wagtail CMS StreamField content to static storage -- with zero page model changes.

## Philosophy

> "Wagtail is designed to produce the kind of sites that designers and front-end developers were already making."
> -- [The Zen of Wagtail](https://docs.wagtail.org/en/stable/getting_started/the_zen_of_wagtail.html)

Modern Wagtail sites often include **per-page styling** -- a landing page with a unique hero, an article with custom typography, or a campaign page with brand-specific CSS. These inline `<style>` and `<script>` tags live naturally inside StreamField blocks, but they carry a cost: no caching, no CDN benefit, and duplicated bytes on every page load.

wagtail-asset-publisher solves this transparently. When a page is published, inline assets are **automatically extracted** from StreamField content, built into static files with content-hashed filenames, and served via `<link>`/`<script src>` references. No page model changes. No template tags. No deployment pipeline.

**Write inline styles in StreamField blocks. Publish. Assets are extracted and served as static files automatically.**

## Key Features

- **Zero-config** -- Add to `INSTALLED_APPS`, add middleware, run migrations. No mixin, no template tags, no model changes
- **Automatic extraction** -- Inline `<style>` and `<script>` tags in StreamField content are extracted at publish time
- **Content-hashed filenames** -- Automatic cache busting: `{page_id}-{hash}.css`
- **Middleware-driven** -- At render time, matched inline tags are stripped and replaced with static file references
- **SHA-256 content matching** -- Only strips tags whose content hash matches published assets; base template tags are untouched
- **Pluggable builders** -- Raw concatenation (default) or Tailwind CSS JIT compilation
- **Pluggable storage** -- Django default storage (S3, GCS, Azure) or local filesystem
- **Cross-package integration** -- Snippet publish triggers asset rebuild for all referencing pages via Wagtail's ReferenceIndex
- **Preview support** -- Inline tags render naturally in preview mode; Tailwind CDN script is auto-injected when using Tailwind builder
- **`data-no-extract` attribute** -- Mark inline tags to skip extraction and keep them inline
- **Asset optimization** -- Optional CSS minification (rcssmin) and JS obfuscation (terser / rjsmin) with graceful fallbacks
- **Strategy pattern architecture** -- Extend with custom builders and storage backends

## Installation

```bash
pip install wagtail-asset-publisher
```

Add to your `INSTALLED_APPS`:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "wagtail_asset_publisher",
    # ...
]
```

Add the middleware:

```python
# settings.py
MIDDLEWARE = [
    # ...
    "wagtail_asset_publisher.middleware.AssetPublisherMiddleware",
]
```

Run migrations:

```bash
python manage.py migrate
```

## Quick Start

That's it. There is no step 2.

Once installed, wagtail-asset-publisher works automatically:

1. Write inline `<style>` or `<script>` tags in your StreamField blocks as usual
2. Publish the page
3. The middleware strips the matched inline tags and injects static file references

View the published page source. You should see something like:

```html
<link rel="stylesheet" href="/media/page-assets/css/42-a1b2c3d4.css">
<script src="/media/page-assets/js/42-e5f6a7b8.js"></script>
```

The original inline tags are gone -- replaced by cached, content-hashed static files.

### How It Works

1. **Publish**: Wagtail fires the `published` signal
2. **Extract**: All StreamField fields on the page are rendered; inline `<style>` and `<script>` tags are parsed out (respecting `data-no-extract`)
3. **Build**: Extracted content is passed to the configured builder (Raw or Tailwind)
4. **Store**: The built output is saved to storage with a content-hashed filename
5. **Record**: A `PublishedAsset` record stores the URL and content hashes for the page
6. **Serve**: On the next request, the middleware looks up published assets, strips inline tags whose SHA-256 hash matches, and injects `<link>`/`<script src>` references

## Configuration

All settings are optional. Configure via the `WAGTAIL_ASSET_PUBLISHER` dict in your Django settings:

```python
# settings.py
WAGTAIL_ASSET_PUBLISHER = {
    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
    "CSS_PREFIX": "page-assets/css/",
    "JS_PREFIX": "page-assets/js/",
    "HASH_LENGTH": 8,
    "TAILWIND_CLI_PATH": None,
    "TAILWIND_CONFIG": None,
    "TAILWIND_BASE_CSS": None,
    "TAILWIND_CDN_URL": "https://unpkg.com/@tailwindcss/browser@4",
    # Asset optimization (requires pip install wagtail-asset-publisher[minify])
    "MINIFY_CSS": True,
    "OBFUSCATE_JS": False,
    "TERSER_PATH": None,
    "TERSER_OPTIONS": ["-c", "-m"],
}
```

### Available Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `CSS_BUILDER` | `"...builders.raw.RawAssetBuilder"` | CSS builder class (dotted path) |
| `JS_BUILDER` | `"...builders.raw.RawAssetBuilder"` | JS builder class (dotted path) |
| `STORAGE_BACKEND` | `"...storage.django_storage.DjangoStorageBackend"` | Storage backend class (dotted path) |
| `CSS_PREFIX` | `"page-assets/css/"` | Path prefix for CSS files in storage |
| `JS_PREFIX` | `"page-assets/js/"` | Path prefix for JS files in storage |
| `HASH_LENGTH` | `8` | Length of the content hash in filenames |
| `TAILWIND_CLI_PATH` | `None` | Path to Tailwind CLI binary (auto-detected if not set) |
| `TAILWIND_CONFIG` | `None` | Path to Tailwind config file |
| `TAILWIND_BASE_CSS` | `None` | Path to base input CSS file for Tailwind |
| `TAILWIND_CDN_URL` | `"https://unpkg.com/@tailwindcss/browser@4"` | Tailwind CDN URL for preview mode |
| `MINIFY_CSS` | `True` | Minify CSS output via rcssmin (requires `minify` extra) |
| `OBFUSCATE_JS` | `False` | Minify/obfuscate JS output via terser or rjsmin (requires `minify` extra) |
| `TERSER_PATH` | `None` | Explicit path to the terser binary (auto-detected if not set) |
| `TERSER_OPTIONS` | `["-c", "-m"]` | CLI options passed to terser |

## Advanced Usage

### The `data-no-extract` Attribute

Add `data-no-extract` to any `<style>` or `<script>` tag to prevent it from being extracted. The tag will remain inline in the rendered HTML.

This is useful for:

- **Critical CSS** that must be inline for above-the-fold rendering
- **Initialization scripts** that must execute before external scripts load
- **Third-party snippets** that should not be bundled

```html
<!-- This will be extracted and published as a static file -->
<style>
  .hero { background: linear-gradient(...); }
</style>

<!-- This stays inline -->
<style data-no-extract>
  .critical-above-fold { display: block; }
</style>

<!-- This stays inline -->
<script data-no-extract>
  window.__INITIAL_STATE__ = { ... };
</script>
```

External scripts (`<script src="...">`) are never extracted regardless of attributes.

### Asset Optimization (CSS Minification and JS Obfuscation)

Install the `minify` extra to enable built-in optimization:

```bash
pip install wagtail-asset-publisher[minify]
```

This installs `rcssmin` and `rjsmin`. For stronger JS minification, also install [terser](https://terser.org/) via npm:

```bash
npm install terser
```

#### CSS Minification

CSS minification is **enabled by default** (`MINIFY_CSS: True`). It uses `rcssmin` to strip whitespace and comments from the built CSS output. If `rcssmin` is not installed, a warning is logged and the unminified output is used instead.

To disable CSS minification:

```python
WAGTAIL_ASSET_PUBLISHER = {
    "MINIFY_CSS": False,
}
```

#### JS Optimization

JS optimization is **disabled by default** (`OBFUSCATE_JS: False`). When enabled, the following fallback chain is used:

1. **terser** (CLI) -- full minification with dead-code elimination and identifier mangling
2. **rjsmin** (Python) -- whitespace and comment stripping; used if terser is not found
3. **no optimization** -- a warning is logged and the original output is used if neither tool is available

To enable JS optimization:

```python
WAGTAIL_ASSET_PUBLISHER = {
    "OBFUSCATE_JS": True,
}
```

**Terser binary discovery order:**

1. `TERSER_PATH` setting (explicit path)
2. `{BASE_DIR}/node_modules/.bin/terser` (local npm install)
3. `terser` on the system `PATH`

To point to a specific terser binary:

```python
WAGTAIL_ASSET_PUBLISHER = {
    "OBFUSCATE_JS": True,
    "TERSER_PATH": "/path/to/node_modules/.bin/terser",
    "TERSER_OPTIONS": ["-c", "-m"],  # compress + mangle (default)
}
```

### Tailwind CSS JIT Mode

For Tailwind mode, install with the `tailwind` extra:

```bash
pip install wagtail-asset-publisher[tailwind]
```

Set up django-tailwind-cli:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_tailwind_cli",
    # ...
]
```

Download the Tailwind CLI binary:

```bash
python manage.py tailwind download_cli
```

> **Note:** `django-tailwind-cli` requires `STATICFILES_DIRS` to be configured. If not already set, add `STATICFILES_DIRS = [BASE_DIR / "static"]` to your settings.

Configure the CSS builder:

```python
# settings.py
WAGTAIL_ASSET_PUBLISHER = {
    "CSS_BUILDER": "wagtail_asset_publisher.builders.tailwind.TailwindCSSBuilder",
    # Optional: path is auto-detected from django-tailwind-cli or PATH
    "TAILWIND_CLI_PATH": "/path/to/tailwindcss",
    "TAILWIND_CONFIG": "tailwind.config.js",
}
```

**How it works:**

1. On page publish, the builder renders the page's full HTML
2. Tailwind CLI scans the HTML for utility classes
3. Only the CSS for classes actually used is generated
4. Any extracted inline `<style>` content is included in the build
5. If the CLI fails, the builder gracefully falls back to raw CSS output

**Preview support:** When using the Tailwind builder, the middleware automatically injects the Tailwind CSS browser CDN script into preview responses. This lets editors see Tailwind utility classes rendered in real time before publishing. The CDN script is never injected in published pages.

### Cross-Package Integration

wagtail-asset-publisher integrates with Wagtail's `published` signal and `ReferenceIndex` to support cross-package workflows.

**Snippet publish cascading:** When a snippet with `DraftStateMixin` (e.g., a reusable content block) is published, the signal handler automatically:

1. Looks up all pages referencing the snippet via `ReferenceIndex`
2. Rebuilds assets for each referencing page

This means if a reusable block containing inline styles is updated, all pages using that block get their assets rebuilt automatically.

### S3 Storage with django-storages

The default `DjangoStorageBackend` delegates to Django's `default_storage`, so it works with any storage backend out of the box:

```python
# settings.py
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": "my-assets-bucket",
        },
    },
}

WAGTAIL_ASSET_PUBLISHER = {
    "CSS_PREFIX": "assets/css/",
    "JS_PREFIX": "assets/js/",
}
```

### Local File Storage

For development without cloud storage, use `LocalFileStorage` which saves assets under `STATIC_ROOT`:

```python
# settings.py
WAGTAIL_ASSET_PUBLISHER = {
    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.local.LocalFileStorage",
}
```

### Custom Builders

Create a custom builder by subclassing `BaseAssetBuilder`:

```python
from wagtail_asset_publisher.builders.base import BaseAssetBuilder


class MinifyingCSSBuilder(BaseAssetBuilder):
    def build(self, html_content, extracted_content, asset_type):
        if not extracted_content:
            return ""
        combined = "\n\n".join(extracted_content)
        return minify(combined)
```

Set `requires_html_content = True` on your builder class if it needs the full page HTML (like the Tailwind builder does for class scanning).

Then configure it:

```python
WAGTAIL_ASSET_PUBLISHER = {
    "CSS_BUILDER": "myapp.builders.MinifyingCSSBuilder",
}
```

### Management Command

The `rebuild_assets` command lets you rebuild published assets in bulk:

```bash
# Rebuild assets for all pages that have existing published assets
python manage.py rebuild_assets

# Rebuild assets for specific pages
python manage.py rebuild_assets --page-ids 42 57 103

# Rebuild assets for ALL live pages (including those without existing assets)
python manage.py rebuild_assets --all

# Preview what would be rebuilt without making changes
python manage.py rebuild_assets --dry-run
```

This is useful after:

- Upgrading the package or changing builder settings
- Migrating storage backends
- Bulk content imports

## Troubleshooting

### Assets Not Building on Publish

**Issue**: You publish a page but no asset files appear in storage.

**Solutions**:
1. Confirm the page has StreamField fields containing inline `<style>` or `<script>` tags
2. Check that the tags don't have `data-no-extract` attribute
3. Verify the middleware is in your `MIDDLEWARE` setting
4. Review Django logs for build errors (logging is under `wagtail_asset_publisher`)

### Inline Tags Not Being Replaced

**Issue**: The page still shows inline `<style>`/`<script>` tags instead of static file references.

**Solutions**:
1. Verify `AssetPublisherMiddleware` is in your `MIDDLEWARE` setting
2. Check that the response Content-Type is `text/html`
3. Ensure the page was published (not just saved as draft)
4. The middleware only activates for Wagtail page responses (requests with a `wagtailpage` attribute)

### Tailwind CLI Not Found

**Issue**: `TailwindCSSBuilder` falls back to raw CSS output.

**Solutions**:
1. Install `django-tailwind-cli` (the CLI path is auto-detected)
2. Or set `TAILWIND_CLI_PATH` explicitly to the binary location
3. Or ensure `tailwindcss` is available on your system `PATH`
4. Confirm `django_tailwind_cli` is included in your `INSTALLED_APPS`
5. Confirm `STATICFILES_DIRS` is configured (required by `django-tailwind-cli`)
6. In Docker/CI environments, run `python manage.py tailwind download_cli` to download the binary
7. The builder logs the error and falls back gracefully to raw CSS

### CSS Not Being Minified

**Issue**: Published CSS files are not minified even though `MINIFY_CSS` is `True`.

**Solutions**:
1. Install the `minify` extra: `pip install wagtail-asset-publisher[minify]`
2. Check Django logs for a warning message containing `rcssmin is not installed`

### JS Not Being Optimized

**Issue**: Published JS files are not minified even though `OBFUSCATE_JS` is `True`.

**Solutions**:
1. Install the `minify` extra: `pip install wagtail-asset-publisher[minify]`
2. For terser-level optimization, ensure terser is available: `npm install terser` or `npm install -g terser`
3. Check Django logs for warnings -- the fallback chain logs each step:
   - `terser failed: ...` means terser was found but errored; rjsmin will be tried
   - `Neither terser nor rjsmin is available. JS optimization skipped.` means neither tool is installed
4. Set `TERSER_PATH` explicitly if terser is installed at a non-standard location

### Snippet Publish Not Rebuilding Pages

**Issue**: Publishing a snippet doesn't rebuild assets for pages that use it.

**Solutions**:
1. Ensure the snippet uses `DraftStateMixin` (the `published` signal only fires for draftable models)
2. Verify `ReferenceIndex` is available (Wagtail 4.1+)

## Requirements

| Python | Django | Wagtail |
|--------|--------|---------|
| 3.10+ | 4.2, 5.1, 5.2 | 6.4, 7.0, 7.2 |

See our [CI configuration](.github/workflows/ci.yml) for the complete compatibility matrix.

## Project Links

- [GitHub Repository](https://github.com/kkm-horikawa/wagtail-asset-publisher)
- [Issue Tracker](https://github.com/kkm-horikawa/wagtail-asset-publisher/issues)
- [Changelog](https://github.com/kkm-horikawa/wagtail-asset-publisher/releases)

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## License

BSD 3-Clause License. See [LICENSE](LICENSE) for details.

## Inspiration

- [Wagtail's built-in static files system](https://docs.wagtail.org/en/stable/advanced_topics/static_files.html) for the foundation
- [django-tailwind-cli](https://github.com/oliverandrich/django-tailwind-cli) for seamless Tailwind CSS integration
- The concept of "publish-time extraction" -- automatically converting inline assets to cached static files at the moment of publishing
