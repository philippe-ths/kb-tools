import unittest

from kb.categories import parse_categories


class ParseCategoriesTest(unittest.TestCase):
    def setUp(self):
        from .fixture import _FILES

        self.cats = parse_categories(_FILES["index.md"])

    def test_section_and_subsection_paths(self):
        paths = [c.path for c in self.cats]
        self.assertEqual(paths, ["Concepts / Greek", "Sources", "Maps"])

    def test_targets_assigned_to_right_category(self):
        greek = self.cats[0]
        self.assertEqual(
            greek.page_targets,
            ["wiki/concept-alpha", "wiki/concept-beta", "wiki/concept-orphan"],
        )

    def test_empty_sections_dropped(self):
        text = "## Empty\n## Real\n- [[wiki/x]]\n"
        cats = parse_categories(text)
        self.assertEqual([c.path for c in cats], ["Real"])

    def test_subsection_resets_on_new_section(self):
        text = (
            "## A\n### sub\n- [[wiki/x]]\n## B\n- [[wiki/y]]\n"
        )
        cats = parse_categories(text)
        self.assertEqual([c.path for c in cats], ["A / sub", "B"])


if __name__ == "__main__":
    unittest.main()
