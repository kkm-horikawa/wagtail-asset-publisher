"""Tests for wagtail_asset_publisher.models module.

Covers the PublishedAsset model and AssetType enum.

Note: DB constraint tests (unique_together, CASCADE) require @pytest.mark.django_db.
Non-DB tests (__str__, defaults, enum) use unsaved model instances only.
"""

import pytest

from wagtail_asset_publisher.models import AssetType, PublishedAsset


class TestAssetType:
    """Tests for the AssetType TextChoices enum."""

    def test_asset_type_css_value(self):
        """AssetType.CSS has value 'css' and label 'CSS'.

        Purpose: Verify the CSS enum variant stores the expected DB value
            and human-readable label.
        Category: Normal case
        Target: AssetType.CSS
        Technique: Equivalence partitioning
        Test data: AssetType.CSS value and label
        """
        assert AssetType.CSS == "css"
        assert AssetType.CSS.label == "CSS"

    def test_asset_type_js_value(self):
        """AssetType.JS has value 'js' and label 'JavaScript'.

        Purpose: Verify the JS enum variant stores the expected DB value
            and human-readable label.
        Category: Normal case
        Target: AssetType.JS
        Technique: Equivalence partitioning
        Test data: AssetType.JS value and label
        """
        assert AssetType.JS == "js"
        assert AssetType.JS.label == "JavaScript"

    def test_asset_type_choices_count(self):
        """AssetType has exactly two choices (CSS and JS).

        Purpose: Guard against accidentally adding or removing choices
            without updating tests.
        Category: Normal case
        Target: AssetType.choices
        Technique: Equivalence partitioning
        Test data: Length of AssetType.choices
        """
        assert len(AssetType.choices) == 2


class TestPublishedAssetStr:
    """Tests for PublishedAsset.__str__ method (no DB required)."""

    def test_published_asset_str_css(self):
        """__str__ returns 'PublishedAsset(42, css)' for CSS asset with page_id=42.

        Purpose: Verify the string representation format for debugging
            and admin display with CSS type.
        Category: Normal case
        Target: PublishedAsset.__str__()
        Technique: Equivalence partitioning
        Test data: Unsaved PublishedAsset with page_id=42, asset_type='css'
        """
        asset = PublishedAsset(page_id=42, asset_type=AssetType.CSS)

        result = str(asset)

        assert result == "PublishedAsset(42, css)"

    def test_published_asset_str_js(self):
        """__str__ returns 'PublishedAsset(7, js)' for JS asset with page_id=7.

        Purpose: Verify the string representation format for JS type.
        Category: Normal case
        Target: PublishedAsset.__str__()
        Technique: Equivalence partitioning
        Test data: Unsaved PublishedAsset with page_id=7, asset_type='js'
        """
        asset = PublishedAsset(page_id=7, asset_type=AssetType.JS)

        result = str(asset)

        assert result == "PublishedAsset(7, js)"


class TestPublishedAssetDefaults:
    """Tests for PublishedAsset field defaults (no DB required)."""

    def test_content_hashes_default_empty_list(self):
        """content_hashes field defaults to an empty list.

        Purpose: Verify that JSONField(default=list) produces an empty list
            for newly instantiated (unsaved) objects.
        Category: Edge case
        Target: PublishedAsset.content_hashes default
        Technique: Boundary value analysis (default value)
        Test data: PublishedAsset() with no arguments
        """
        asset = PublishedAsset()

        assert asset.content_hashes == []


@pytest.mark.django_db
class TestPublishedAssetDBConstraints:
    """Tests for DB-level constraints that require actual database access."""

    def test_unique_together_constraint(self):
        """Cannot create two PublishedAssets for same page + asset_type.

        Purpose: Verify the unique_together constraint prevents duplicate
            entries, ensuring each page has at most one CSS and one JS asset.
        Category: Abnormal case (constraint violation)
        Target: PublishedAsset unique_together = [("page", "asset_type")]
        Technique: Error guessing (duplicate insert)
        Test data: Two CSS PublishedAssets for the same page
        """
        from django.db import IntegrityError
        from wagtail.models import Page

        root = Page.objects.first()
        page = root.add_child(instance=Page(title="Test", slug="test"))

        PublishedAsset.objects.create(
            page=page,
            asset_type=AssetType.CSS,
            url="https://example.com/a.css",
            content_hashes=["hash1"],
        )

        with pytest.raises(IntegrityError):
            PublishedAsset.objects.create(
                page=page,
                asset_type=AssetType.CSS,
                url="https://example.com/b.css",
                content_hashes=["hash2"],
            )

    def test_cascade_delete(self):
        """Deleting a page cascades to its PublishedAssets.

        Purpose: Verify that on_delete=CASCADE on the page ForeignKey
            removes PublishedAsset records when the page is deleted.
        Category: Normal case (cleanup behavior)
        Target: PublishedAsset.page ForeignKey on_delete=CASCADE
        Technique: State transition (page exists -> deleted -> assets gone)
        Test data: Page with one CSS PublishedAsset
        """
        from wagtail.models import Page

        root = Page.objects.first()
        page = root.add_child(instance=Page(title="Cascade", slug="cascade"))
        page_id = page.pk

        PublishedAsset.objects.create(
            page=page,
            asset_type=AssetType.CSS,
            url="https://example.com/c.css",
            content_hashes=["hash1"],
        )
        assert PublishedAsset.objects.filter(page_id=page_id).count() == 1

        page.delete()

        assert PublishedAsset.objects.filter(page_id=page_id).count() == 0

    def test_different_asset_types_allowed_for_same_page(self):
        """Same page can have both a CSS and JS PublishedAsset.

        Purpose: Verify that unique_together permits different asset_type
            values for the same page, which is the expected behavior.
        Category: Normal case
        Target: PublishedAsset unique_together
        Technique: Equivalence partitioning (valid combination)
        Test data: One CSS and one JS asset for the same page
        """
        from wagtail.models import Page

        root = Page.objects.first()
        page = root.add_child(instance=Page(title="Both", slug="both"))

        PublishedAsset.objects.create(
            page=page,
            asset_type=AssetType.CSS,
            url="https://example.com/d.css",
            content_hashes=["css_hash"],
        )
        PublishedAsset.objects.create(
            page=page,
            asset_type=AssetType.JS,
            url="https://example.com/d.js",
            content_hashes=["js_hash"],
        )

        assert PublishedAsset.objects.filter(page=page).count() == 2
